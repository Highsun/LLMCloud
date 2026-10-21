"""Per-request context, also propagated into AnyIO service threads."""

from contextvars import ContextVar
import logging

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"{msg} request_id={request_id_context.get()}", kwargs
