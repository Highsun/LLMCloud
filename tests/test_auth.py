"""Account/session persistence and ownership isolation against real HTTP/SQLite."""

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from starlette.testclient import TestClient

from backend.app.core.auth_migration import AuthSchemaMigrationRequired, migrate_auth
from backend.app.core.config import Settings
from backend.app.core.database import create_database_engine
from backend.app.main import create_app
from backend.app.models.entities import AuthSession, Dataset, User
from backend.app.services.auth import COOKIE, password_hash, verify_password

PASSWORD = "a-long-independent-password"
RAW = b'{"instruction":"what is cloud?","output":"on demand resources"}\n'


class Publisher:
    def publish(self, *_args):
        return "accepted"


class AuthHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(_env_file=None, data_dir=self.root / "data", log_dir=self.root / "logs",
            database_url="", auth_enabled=True)
        self.app = create_app(self.settings, task_publisher=Publisher())
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def account(self, username="alice"):
        body = {"username": username, "password": PASSWORD}
        response = self.client.post("/api/v1/auth/register", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post("/api/v1/auth/login", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def upload(self):
        response = self.client.post("/api/v1/datasets", files={"file": ("train.jsonl", RAW)})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_unauthenticated_and_disabled_mode(self):
        self.assertEqual(self.client.get("/api/v1/auth/config").json(), {"enabled": True})
        for url in ("datasets", "tasks", "auth/me"):
            response = self.client.get("/api/v1/" + url)
            self.assertEqual(response.status_code, 401, response.text)
            self.assertEqual(response.json()["error"]["code"], "AUTH_REQUIRED")
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)

    def test_registration_password_session_logout_and_revoke(self):
        account = self.account("Alice")
        self.assertEqual(account["username"], "alice")
        cookie = self.client.cookies.get(COOKIE)
        sessions = self.app.state.auth_service.sessions
        with sessions() as session:
            user = session.get(User, account["id"])
            self.assertNotIn(PASSWORD, user.password_hash)
            self.assertTrue(verify_password(PASSWORD, user.password_hash))
            record = session.get(AuthSession, sha256(cookie.encode()).hexdigest())
            self.assertEqual(record.user_id, user.id)
            self.assertNotEqual(record.token_hash, cookie)
        response = self.client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertNotEqual(cookie, self.client.cookies.get(COOKIE))
        self.assertIsNone(self.app.state.auth_service.authenticate(cookie))
        new_cookie = self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.post("/api/v1/auth/logout").status_code, 204)
        self.assertIsNone(self.app.state.auth_service.authenticate(new_cookie))
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        # Activation preserves a historical display name, including its case.
        with sessions.begin() as session:
            session.get(User, account["id"]).username = "Alice"
        login = self.client.post("/api/v1/auth/login", json={"username": "ALICE", "password": PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(self.client.post("/api/v1/auth/register", json={"username": "alice", "password": PASSWORD}).status_code, 409)

    def test_bad_password_duplicate_validation_and_rate_limit(self):
        self.account()
        bad = self.client.post("/api/v1/auth/login", json={"username": "alice", "password": "invalid-password"})
        missing = self.client.post("/api/v1/auth/login", json={"username": "missing", "password": "invalid-password"})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.json()["error"]["code"], missing.json()["error"]["code"])
        duplicate = self.client.post("/api/v1/auth/register", json={"username": "ALICE", "password": PASSWORD})
        self.assertEqual(duplicate.status_code, 409)
        for password in ("short", "x" * 129):
            self.assertEqual(self.client.post("/api/v1/auth/register", json={"username": "new", "password": password}).status_code, 422)
        self.app.state.auth_service._attempts.clear()
        for _ in range(10):
            self.app.state.auth_service.throttle("limited-client")
        from backend.app.services.errors import DatasetServiceError
        with self.assertRaises(DatasetServiceError) as denied:
            self.app.state.auth_service.throttle("limited-client")
        self.assertEqual(denied.exception.status_code, 429)

    def test_expiry_and_csrf_cors(self):
        self.account()
        response = self.client.get("/api/v1/auth/me", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers={"Origin": "https://attacker.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        with patch("backend.app.services.auth.time", return_value=10**12):
            self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_owner_isolation_all_resource_routes_and_idempotency(self):
        alice = self.account()
        dataset = self.upload()
        key = str(uuid4())
        payload = {"dataset_id": dataset["id"], "base_model": "Qwen/Qwen2.5-0.5B-Instruct", "config": {}}
        response = self.client.post("/api/v1/tasks", json=payload, headers={"Idempotency-Key": key})
        self.assertEqual(response.status_code, 202, response.text)
        task_id = response.json()["id"]
        self.assertEqual(self.client.get("/api/v1/tasks").json()["total"], 1)
        self.client.post("/api/v1/auth/logout")
        self.account("bob")
        self.assertEqual(self.client.get("/api/v1/datasets").json()["total"], 0)
        self.assertEqual(self.client.get("/api/v1/tasks").json()["total"], 0)
        for path in (f"datasets/{dataset['id']}", f"tasks/{task_id}", f"tasks/{task_id}/metrics",
                     f"tasks/{task_id}/logs", f"tasks/{task_id}/adapter"):
            response = self.client.get("/api/v1/" + path)
            self.assertEqual(response.status_code, 404, (path, response.text))
        response = self.client.post("/api/v1/inference", json={"task_id": task_id, "prompt": "what is cloud?"})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.client.post("/api/v1/tasks", json=payload).status_code, 404)
        replay = self.client.post("/api/v1/tasks", json=payload, headers={"Idempotency-Key": key})
        self.assertEqual(replay.status_code, 409, replay.text)
        self.assertNotIn(task_id, replay.text)
        with self.app.state.auth_service.sessions() as session:
            self.assertEqual(session.get(Dataset, dataset["id"]).user_id, alice["id"])

    def test_persistence_across_api_restart(self):
        account = self.account()
        self.upload()
        cookies = dict(self.client.cookies)
        self.client.__exit__(None, None, None)
        self.app = create_app(self.settings, task_publisher=Publisher())
        self.client = TestClient(self.app, cookies=cookies)
        self.client.__enter__()
        self.assertEqual(self.client.get("/api/v1/auth/me").json(), account)
        self.assertEqual(self.client.get("/api/v1/datasets").json()["total"], 1)

    def test_oversized_and_duplicate_json_body(self):
        response = self.client.post("/api/v1/auth/login", content='{"username":"alice","username":"bob","password":"' + PASSWORD + '"}',
            headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/v1/auth/register", content=b"x" * 65537, headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)

    def test_invalid_hashes_bounded_parameters_and_authenticated_invalid_ids(self):
        for malformed in (None, "", 123, "plaintext", "scrypt$999999999$8$1$aa$bb", "scrypt$16384$8$1$" + "g" * 32 + "$" + "f" * 128):
            self.assertFalse(verify_password(PASSWORD, malformed))
        self.assertFalse(verify_password("constant-dummy-password-for-timing", ""))
        first, second = password_hash(PASSWORD), password_hash(PASSWORD)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(PASSWORD, first))
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, auth_enabled=True, cors_origins=["*"])
        self.account()
        self.assertEqual(self.client.get("/api/v1/tasks/not-a-uuid/metrics").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/tasks/00000000-0000-1000-8000-000000000000/logs").status_code, 422)


class AuthMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "old.sqlite3"
        self.engine = create_database_engine(f"sqlite:///{self.db}")
        self.user_id, self.dataset_id = str(uuid4()), str(uuid4())
        with sqlite3.connect(self.db) as connection:
            connection.executescript("CREATE TABLE users(id VARCHAR(36) NOT NULL PRIMARY KEY, username VARCHAR(64) NOT NULL UNIQUE, created_at DATETIME NOT NULL);"
                "CREATE TABLE datasets(id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) REFERENCES users(id));")
            connection.execute("INSERT INTO users VALUES (?,?,?)", (self.user_id, "historical", "2026-11-15 00:00:00"))
            connection.execute("INSERT INTO datasets VALUES (?,NULL)", (self.dataset_id,))

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_check_backup_apply_idempotency_and_explicit_ownership(self):
        before = self.db.read_bytes()
        report = migrate_auth(self.engine, self.root)
        self.assertEqual(report.state, "ready")
        self.assertEqual(report.unowned_datasets, 1)
        self.assertEqual(before, self.db.read_bytes())
        with self.assertRaises(ValueError):
            migrate_auth(self.engine, self.root, apply=True)
        report = migrate_auth(self.engine, self.root, apply=True, services_stopped=True)
        self.assertEqual(report.state, "applied")
        with sqlite3.connect(report.backup_path) as backup:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(backup.execute("SELECT * FROM users").fetchone(), (self.user_id, "historical", "2026-11-15 00:00:00"))
            self.assertNotIn("password_hash", {row[1] for row in backup.execute("PRAGMA table_info(users)")})
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT user_id FROM datasets").fetchone(), (None,))
            self.assertEqual(connection.execute("SELECT password_hash FROM users").fetchone(), (None,))
        self.assertEqual(migrate_auth(self.engine, self.root, apply=True, services_stopped=True).state, "current")
        report = migrate_auth(self.engine, self.root, apply=True, services_stopped=True,
            assign_to_user=self.user_id, dataset_ids=[self.dataset_id])
        self.assertEqual(report.assigned_datasets, 1)
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT user_id FROM datasets").fetchone(), (self.user_id,))

    def test_unknown_schema_and_wrong_owner_block_without_mutation(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("ALTER TABLE users ADD COLUMN strange TEXT")
        before = self.db.read_bytes()
        report = migrate_auth(self.engine, self.root, apply=True, services_stopped=True)
        self.assertEqual(report.state, "unsupported_schema")
        self.assertEqual(before, self.db.read_bytes())

    def test_startup_requires_explicit_migration_when_enabled(self):
        from backend.app.core.auth_migration import require_auth_schema
        with self.assertRaises(AuthSchemaMigrationRequired):
            require_auth_schema(self.engine)

    def test_explicit_password_activation_backup_and_session_revocation(self):
        from scripts.set_user_password import set_user_password
        migrate_auth(self.engine, self.root, apply=True, services_stopped=True)
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO auth_sessions VALUES (?,?,?)", ("a" * 64, self.user_id, 10**12))
        with self.assertRaises(ValueError):
            set_user_password(self.engine, self.root, self.user_id, PASSWORD)
        with self.assertRaises(ValueError):
            set_user_password(self.engine, self.root, self.user_id, "too-short", services_stopped=True)
        result = set_user_password(self.engine, self.root, self.user_id, PASSWORD, services_stopped=True)
        self.assertEqual(result["revoked_sessions"], 1)
        with sqlite3.connect(self.db) as connection:
            row = connection.execute("SELECT username,password_hash,created_at FROM users WHERE id=?", (self.user_id,)).fetchone()
            self.assertEqual((row[0], row[2]), ("historical", "2026-11-15 00:00:00"))
            self.assertTrue(verify_password(PASSWORD, row[1]))
            self.assertEqual(connection.execute("SELECT count(*) FROM auth_sessions").fetchone(), (0,))
        with sqlite3.connect(result["backup_path"]) as backup:
            self.assertEqual(backup.execute("SELECT password_hash FROM users").fetchone(), (None,))
            self.assertEqual(backup.execute("SELECT count(*) FROM auth_sessions").fetchone(), (1,))


if __name__ == "__main__":
    unittest.main()
