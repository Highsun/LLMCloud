"""Password verification and SQL-backed, revocable browser sessions."""

from contextlib import contextmanager
from hashlib import pbkdf2_hmac, sha256
from hmac import compare_digest
import re
from secrets import token_bytes, token_urlsafe
from threading import BoundedSemaphore, Lock
from time import monotonic, time

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.app.models.account_schemas import CurrentAccount
from backend.app.models.entities import AccountSession, User
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.services.errors import DatasetServiceError

SESSION_COOKIE = "llmcloud_session"
SESSION_SECONDS = 24 * 60 * 60
PASSWORD_ROUNDS = 600_000
TOKEN_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}")
DUMMY_HASH = f"{'00' * 16}:{'00' * 32}"


def auth_required():
    return DatasetServiceError(ApiErrorCode.AUTH_REQUIRED, "请登录后继续。", 401)


def _invalid_credentials():
    return DatasetServiceError(ApiErrorCode.INVALID_CREDENTIALS, "用户名或密码错误。", 401)


def _throttled():
    return DatasetServiceError(ApiErrorCode.AUTH_THROTTLED, "尝试次数过多，请稍后重试。", 429)


def _password_key(password, salt):
    return pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS).hex()


def _token_digest(token):
    return sha256(token.encode("ascii")).hexdigest() if token and TOKEN_FORMAT.fullmatch(token) else None


class AccountService:
    def __init__(self, sessions):
        self.sessions = sessions
        self._attempts = {}
        self._attempt_lock = Lock()
        self._password_slots = BoundedSemaphore(4)

    @contextmanager
    def _session(self):
        try:
            with self.sessions.begin() as session:
                yield session
        except IntegrityError:
            raise
        except SQLAlchemyError:
            raise DatasetServiceError(ApiErrorCode.DATABASE_UNAVAILABLE, "账号存储暂时不可用。", 503) from None

    @contextmanager
    def _password_attempt(self, source):
        with self._attempt_lock:
            now = monotonic()
            if len(self._attempts) >= 1024:
                self._attempts = {key: value for key, value in self._attempts.items() if value[0] > now}
            expires, attempts = self._attempts.get(source, (now + 60, 0))
            if expires <= now:
                expires, attempts = now + 60, 0
            if attempts >= 15 or (len(self._attempts) >= 1024 and source not in self._attempts):
                raise _throttled()
            self._attempts[source] = expires, attempts + 1
        if not self._password_slots.acquire(blocking=False):
            raise _throttled()
        try:
            yield
        finally:
            self._password_slots.release()

    def _new_session(self, session, account, previous_token):
        previous_digest = _token_digest(previous_token)
        if previous_digest:
            session.execute(delete(AccountSession).where(AccountSession.token_digest == previous_digest))
        token = token_urlsafe(32)
        session.add(AccountSession(token_digest=_token_digest(token), user_id=str(account.id),
                                   expires_at=int(time()) + SESSION_SECONDS))
        return account, token

    def register(self, body, source, previous_token):
        with self._password_attempt(source):
            salt = token_bytes(16)
            password_hash = f"{salt.hex()}:{_password_key(body.password, salt)}"
        try:
            with self._session() as session:
                user = User(username=body.username, display_name=body.username, password_hash=password_hash)
                session.add(user)
                session.flush()
                return self._new_session(session, CurrentAccount.from_user(user), previous_token)
        except IntegrityError:
            with self._session() as session:
                if session.scalar(select(User.id).where(User.username == body.username)) is not None:
                    raise DatasetServiceError(ApiErrorCode.USERNAME_TAKEN, "该用户名已被使用。", 409) from None
            raise DatasetServiceError(ApiErrorCode.DATABASE_UNAVAILABLE, "暂时无法创建账号。", 503) from None

    def login(self, body, source, previous_token):
        with self._password_attempt(source):
            with self._session() as session:
                user = session.scalar(select(User).where(User.username == body.username))
                password_hash = user.password_hash if user else None
                account = CurrentAccount.from_user(user) if password_hash else None
            salt, expected = (password_hash or DUMMY_HASH).split(":", 1)
            if not compare_digest(_password_key(body.password, bytes.fromhex(salt)), expected) or account is None:
                raise _invalid_credentials()
        with self._session() as session:
            return self._new_session(session, account, previous_token)

    def current(self, token):
        digest = _token_digest(token)
        if not digest:
            raise auth_required()
        with self._session() as session:
            user = session.scalar(select(User).join(AccountSession, AccountSession.user_id == User.id)
                .where(AccountSession.token_digest == digest, AccountSession.expires_at > int(time())))
            if user is None or not user.password_hash:
                raise auth_required()
            return CurrentAccount.from_user(user)

    def update_profile(self, user_id, body):
        with self._session() as session:
            user = session.get(User, str(user_id))
            if user is None:
                raise auth_required()
            user.display_name = body.display_name
            return CurrentAccount.from_user(user)

    def logout(self, token):
        digest = _token_digest(token)
        if digest:
            with self._session() as session:
                session.execute(delete(AccountSession).where(AccountSession.token_digest == digest))

    def prune_expired(self):
        with self._session() as session:
            session.execute(delete(AccountSession).where(AccountSession.expires_at <= int(time())))
