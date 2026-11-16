"""Opt-in account API and ownership dependencies for the existing resources."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from backend.app.api.tasks import parse_json_body, parse_query
from backend.app.models.error_schemas import ApiErrorCode, ErrorResponse
from backend.app.services.auth import COOKIE, failure, validate_password

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=12, max_length=128, repr=False,
        json_schema_extra={"writeOnly": True, "format": "password"})

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        return value.lower()

    @field_validator("password")
    @classmethod
    def bound_password_bytes(cls, value):
        return validate_password(value)


class PublicUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    username: str


def check_origin(request):
    origin = request.headers.get("origin")
    allowed = request.app.state.settings.cors_origins
    local_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin is not None and origin not in [*allowed, local_origin]:
        raise failure(ApiErrorCode.ORIGIN_REJECTED, "请求来源不受信任。", 403)
    # SameSite cookies plus an explicit fetch-metadata rejection also protect
    # unsafe requests with no Origin header in supporting browsers.
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise failure(ApiErrorCode.ORIGIN_REJECTED, "请求来源不受信任。", 403)


async def require_user(request: Request):
    if not request.app.state.settings.auth_enabled:
        return None
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_origin(request)
    if not hasattr(request.state, "auth_user"):
        request.state.auth_user = await run_in_threadpool(request.app.state.auth_service.authenticate,
            request.cookies.get(COOKIE))
    if request.state.auth_user is None:
        raise failure(ApiErrorCode.AUTH_REQUIRED, "请先登录。", 401)
    return request.state.auth_user


async def authorize_task(request: Request, task_id):
    user = await require_user(request)
    if user is not None:
        try:
            if UUID(str(task_id)).version != 4:
                return
        except (ValueError, TypeError):
            return  # The path/body schema reports the standard validation error.
        repository = request.app.state.task_repository.for_user(user["id"])
        row = await run_in_threadpool(repository.get_detail, task_id)
        if row is None:
            raise failure(ApiErrorCode.TASK_NOT_FOUND, "训练任务不存在。", 404)


async def enabled(request: Request):
    if not request.app.state.settings.auth_enabled:
        raise failure(ApiErrorCode.AUTH_DISABLED, "当前为单用户演示模式，未启用账户。", 503)
    if request.method == "POST":
        check_origin(request)


ERRORS = {status: {"model": ErrorResponse} for status in (401, 403, 409, 413, 422, 429, 503)}
CREDENTIAL_BODY = {"requestBody": {"required": True, "content": {
    "application/json": {"schema": Credentials.model_json_schema()}}}}


@router.get("/config")
async def config(request: Request):
    return {"enabled": request.app.state.settings.auth_enabled}


@router.post("/register", status_code=201, response_model=PublicUser, dependencies=[Depends(enabled)], responses=ERRORS, openapi_extra=CREDENTIAL_BODY)
async def register(request: Request):
    parse_query(request)
    await run_in_threadpool(request.app.state.auth_service.throttle, request.client.host if request.client else "unknown")
    body = await parse_json_body(request, Credentials)
    return await run_in_threadpool(request.app.state.auth_service.register, body.username, body.password)


@router.post("/login", response_model=PublicUser, dependencies=[Depends(enabled)], responses=ERRORS, openapi_extra=CREDENTIAL_BODY)
async def login(request: Request, response: Response):
    parse_query(request)
    await run_in_threadpool(request.app.state.auth_service.throttle, request.client.host if request.client else "unknown")
    body = await parse_json_body(request, Credentials)
    user, token = await run_in_threadpool(request.app.state.auth_service.login, body.username, body.password,
        request.cookies.get(COOKIE))
    response.set_cookie(COOKIE, token, max_age=request.app.state.settings.auth_session_seconds,
        httponly=True, secure=request.app.state.settings.auth_cookie_secure, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return user


@router.get("/me", response_model=PublicUser, dependencies=[Depends(enabled)], responses=ERRORS)
async def me(response: Response, user: Annotated[dict, Depends(require_user)]):
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/logout", status_code=204, dependencies=[Depends(enabled)], responses=ERRORS)
async def logout(request: Request, response: Response):
    await run_in_threadpool(request.app.state.auth_service.logout, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=request.app.state.settings.auth_cookie_secure,
        samesite="strict")
    response.headers["Cache-Control"] = "no-store"
