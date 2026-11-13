"""Pure ASGI middleware: streaming limits, safe failures, and request correlation."""

import logging
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import ClientDisconnect

from backend.app.api.errors import detail, error_response
from backend.app.core.dataset_contract import MAX_MULTIPART_BYTES
from backend.app.core.task_contract import MAX_TASK_BODY_BYTES
from backend.app.core.request_context import RequestLogger, request_id_context
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.models.inference_schemas import MAX_INFERENCE_BODY_BYTES
from backend.app.services.errors import DatasetServiceError

logger = RequestLogger(logging.getLogger(__name__), {})


class RequestIDMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        identifier = str(uuid4())
        token = request_id_context.set(identifier)
        scope.setdefault("state", {})["request_id"] = identifier

        async def with_request_id(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = identifier
            await send(message)

        try:
            await self.app(scope, receive, with_request_id)
        finally:
            request_id_context.reset(token)


class APIErrorMiddleware:
    """Runs inside CORS, so even early upload failures and 500s get CORS headers."""

    def __init__(self, app, *, upload_path: str, task_path: str | None = None,
                 inference_path: str | None = None):
        self.app = app
        self.upload_path = upload_path
        self.task_path = task_path
        self.inference_path = inference_path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False
        path = scope["path"].rstrip("/")
        is_inference = scope["method"] == "POST" and path == self.inference_path

        async def track_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if is_inference:
                    MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        json_limits = {self.task_path: MAX_TASK_BODY_BYTES, self.inference_path: MAX_INFERENCE_BODY_BYTES}
        is_json = path in json_limits
        limit = json_limits.get(path, MAX_MULTIPART_BYTES)

        def too_large():
            if is_json:
                label = "任务" if path == self.task_path else "推理"
                return DatasetServiceError(ApiErrorCode.REQUEST_TOO_LARGE, f"{label}请求正文超过允许大小。", 413,
                    [detail(["body"], "request_too_large", f"{label} JSON 请求正文不能超过 64 KiB。")])
            return DatasetServiceError(
                ApiErrorCode.UPLOAD_TOO_LARGE, "上传请求体超过允许大小。", 413,
                [detail(["body"], "file_too_large", "整个上传请求体超过允许大小。")],
            )

        try:
            bounded_receive = receive
            if scope["method"] == "POST" and (path == self.upload_path or is_json):
                lengths = Headers(scope=scope).getlist("content-length")
                if lengths:
                    if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                        raise DatasetServiceError(ApiErrorCode.HTTP_ERROR, "Content-Length 不合法。", 400)
                    # Avoid converting arbitrarily long decimal headers to Python int.
                    value = lengths[0].lstrip("0") or "0"
                    cap = str(limit)
                    if len(value) > len(cap) or (len(value) == len(cap) and value > cap):
                        raise too_large()
                received = 0

                async def bounded_receive():
                    nonlocal received
                    message = await receive()
                    if message["type"] == "http.request":
                        received += len(message.get("body", b""))
                        if received > limit:
                            raise too_large()
                    return message

            await self.app(scope, bounded_receive, track_send)
        except ClientDisconnect:
            logger.info("request_disconnected")
        except Exception as error:
            if started:
                raise  # Never send a second response after headers have been sent.
            if not isinstance(error, DatasetServiceError):
                logger.error("request_failed reason=%s", type(error).__name__)
                error = DatasetServiceError(ApiErrorCode.INTERNAL_ERROR, "服务器内部错误，请稍后重试。", 500)
            await error_response(error)(scope, receive, track_send)
