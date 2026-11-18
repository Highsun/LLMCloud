"""Password and opaque-session persistence; tokens and passwords are never logged."""

from collections import OrderedDict, deque
from hashlib import pbkdf2_hmac, scrypt, sha256
import hmac
import re
import secrets
import threading
from time import monotonic, time

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.app.models.entities import AuthSession, User
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.services.errors import DatasetServiceError

COOKIE = "llmcloud_session"
LEGACY_PASSWORD = re.compile(r"([0-9a-f]{32}):([0-9a-f]{64})")


def failure(code, message, status):
    return DatasetServiceError(code, message, status)


def validate_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128 or len(password.encode("utf-8")) > 512:
        raise ValueError("Password must contain 12–128 characters and at most 512 UTF-8 bytes")
    return password


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, maxmem=64 * 1024 * 1024)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


_DUMMY = password_hash("constant-dummy-password-for-timing")


def verify_password(password, encoded):
    encoded = encoded if isinstance(encoded, str) and encoded else None
    legacy = LEGACY_PASSWORD.fullmatch(encoded or "")
    if legacy:
        salt, digest = legacy.groups()
        actual = pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 600_000)
        return hmac.compare_digest(actual.hex(), digest)
    try:
        parts = (encoded or _DUMMY).split("$")
        if (len(parts) != 6 or parts[:4] != ["scrypt", "16384", "8", "1"]
                or len(parts[4]) != 32 or len(parts[5]) != 128):
            parts = _DUMMY.split("$")
            encoded = None
        actual = password_hash(password, bytes.fromhex(parts[4]))
        return hmac.compare_digest(actual, "$".join(parts)) and encoded is not None
    except (ValueError, TypeError):
        # Do the normal cost even for a corrupt stored hash.
        password_hash(password, bytes(16))
        return False


def public_user(user):
    return {"id": user.id, "username": user.username, "display_name": user.display_name or user.username}


class AuthService:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings
        self._attempts = OrderedDict()
        self._lock = threading.Lock()

    def throttle(self, client):
        now = monotonic()
        with self._lock:
            attempts = self._attempts.pop(client, deque())
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            denied = len(attempts) >= 10
            if not denied:
                attempts.append(now)
            self._attempts[client] = attempts
            while len(self._attempts) > 4096:
                self._attempts.popitem(last=False)
        if denied:
            raise failure(ApiErrorCode.AUTH_RATE_LIMITED, "操作过于频繁，请一分钟后重试。", 429)

    def register(self, username, password):
        encoded = password_hash(password)
        try:
            with self.sessions.begin() as session:
                if session.scalar(select(User.id).where(func.lower(User.username) == username)) is not None:
                    raise failure(ApiErrorCode.USERNAME_UNAVAILABLE, "用户名不可用。", 409)
                user = User(username=username, password_hash=encoded)
                session.add(user)
                session.flush()
                return public_user(user)
        except IntegrityError:
            raise failure(ApiErrorCode.USERNAME_UNAVAILABLE, "用户名不可用。", 409) from None
        except SQLAlchemyError:
            raise failure(ApiErrorCode.DATABASE_UNAVAILABLE, "账户存储暂时不可用。", 503) from None

    def login(self, username, password, old_token=None):
        try:
            with self.sessions() as session:
                user = session.scalar(select(User).where(func.lower(User.username) == username))
                if not verify_password(password, user.password_hash if user else None):
                    raise failure(ApiErrorCode.INVALID_CREDENTIALS, "用户名或密码错误。", 401)
                if LEGACY_PASSWORD.fullmatch(user.password_hash):
                    user.password_hash = password_hash(password)
                token = secrets.token_urlsafe(32)
                if old_token:
                    session.execute(delete(AuthSession).where(AuthSession.token_hash == sha256(old_token.encode()).hexdigest()))
                session.execute(delete(AuthSession).where(AuthSession.expires_at <= time()))
                session.add(AuthSession(token_hash=sha256(token.encode()).hexdigest(), user_id=user.id,
                    expires_at=time() + self.settings.auth_session_seconds))
                result = public_user(user)
                session.commit()
                return result, token
        except SQLAlchemyError:
            raise failure(ApiErrorCode.DATABASE_UNAVAILABLE, "账户存储暂时不可用。", 503) from None

    def authenticate(self, token):
        if not token or len(token) > 100:
            return None
        try:
            with self.sessions() as session:
                row = session.execute(select(User.id, User.username, User.display_name).join(AuthSession, AuthSession.user_id == User.id)
                    .where(AuthSession.token_hash == sha256(token.encode()).hexdigest(), AuthSession.expires_at > time())).first()
                return None if row is None else public_user(row)
        except SQLAlchemyError:
            raise failure(ApiErrorCode.DATABASE_UNAVAILABLE, "账户存储暂时不可用。", 503) from None

    def update_profile(self, user_id, display_name):
        try:
            with self.sessions.begin() as session:
                user = session.get(User, user_id)
                if user is None:
                    raise failure(ApiErrorCode.AUTH_REQUIRED, "请先登录。", 401)
                user.display_name = display_name
                return public_user(user)
        except SQLAlchemyError:
            raise failure(ApiErrorCode.DATABASE_UNAVAILABLE, "账户存储暂时不可用。", 503) from None

    def logout(self, token):
        try:
            with self.sessions.begin() as session:
                if token and len(token) <= 100:
                    session.execute(delete(AuthSession).where(AuthSession.token_hash == sha256(token.encode()).hexdigest()))
        except SQLAlchemyError:
            raise failure(ApiErrorCode.DATABASE_UNAVAILABLE, "账户存储暂时不可用。", 503) from None
