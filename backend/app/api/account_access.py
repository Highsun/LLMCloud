"""Shared browser session and owner checks for protected HTTP endpoints."""

from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from starlette.concurrency import run_in_threadpool

from backend.app.core.task_protocols import TaskStoreError
from backend.app.models.account_schemas import CurrentAccount
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.services.accounts import SESSION_COOKIE
from backend.app.services.errors import DatasetServiceError
from backend.app.services.tasks import database_error

BrowserSession = Annotated[str | None, Security(APIKeyCookie(
    name=SESSION_COOKIE, scheme_name="AccountSession", auto_error=False))]


def require_browser_action(request: Request):
    origin = request.headers.get("origin")
    same_origin = f"{request.url.scheme}://{request.url.netloc}"
    allowed = request.app.state.settings.cors_origins
    if (request.headers.get("X-LLMCloud-Request") != "1"
            or request.headers.get("Sec-Fetch-Site") == "cross-site"
            or (origin and origin != same_origin and origin not in allowed)):
        raise DatasetServiceError(ApiErrorCode.REQUEST_ORIGIN_REJECTED, "此页面无法发起该操作，请从工作台重试。", 403)


def require_account(request: Request, token: BrowserSession) -> CurrentAccount:
    account = request.app.state.account_service.current(token)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        require_browser_action(request)
    return account


SignedIn = Annotated[CurrentAccount, Depends(require_account)]


async def require_task_owner(request, task_id, account):
    try:
        owned = await run_in_threadpool(request.app.state.task_repository.owns_task, task_id, account.id)
    except TaskStoreError:
        raise database_error() from None
    if not owned:
        raise DatasetServiceError(ApiErrorCode.TASK_NOT_FOUND, "训练任务不存在。", 404)
