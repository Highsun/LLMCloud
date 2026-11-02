"""One bounded Redis/Celery publish attempt. Never imports Worker or Trainer."""

import logging
from urllib.parse import urlsplit

from backend.app.core.task_contract import PublishOutcome
from backend.app.core.request_context import RequestLogger
from backend.app.services.task_records import identifier

logger = RequestLogger(logging.getLogger(__name__), {})


class CeleryPublisher:
    def __init__(self, settings):
        self.settings = settings

    def publish(self, task_id, celery_task_id):
        connection = application = None
        sending = False
        try:
            task_id, celery_task_id = identifier(task_id), identifier(celery_task_id)
            url = self.settings.redis_url
            if urlsplit(url).scheme not in {"redis", "rediss", "redis+socket"} or ";" in url:
                raise ValueError("A single Redis broker URL is required")
            from celery import Celery
            from kombu import Connection, Producer
            from redis.backoff import NoBackoff
            from redis.retry import Retry

            timeout = self.settings.task_publish_timeout_seconds
            options = {"socket_connect_timeout": timeout, "socket_timeout": timeout,
                "retry_on_timeout": False, "health_check_interval": 0,
                "max_retries": 0, "interval_start": 0, "interval_step": 0, "interval_max": 0}
            connection = Connection(url, connect_timeout=timeout, transport_options=options)
            # Connection.connect() retries once in the locked Kombu; use zero retries explicitly.
            connection.ensure_connection(max_retries=0)
            connection.default_channel.client.set_retry(Retry(NoBackoff(), 0))
            application = Celery("llmcloud-api-publisher", broker=url, set_as_current=False)
            application.conf.update(task_serializer="json", accept_content=["json"],
                task_publish_retry=False, broker_pool_limit=0, broker_transport_options=options,
                broker_connection_timeout=timeout, task_protocol=2, enable_utc=True, timezone="UTC")
            producer = Producer(connection, serializer="json")
            sending = True
            application.send_task("worker.train", args=[task_id], task_id=celery_task_id,
                producer=producer, queue=self.settings.training_queue, serializer="json",
                retry=False, ignore_result=True, add_to_parent=False)
            return PublishOutcome.ACCEPTED
        except Exception as error:
            logger.warning("task_publish_failed task_id=%s phase=%s reason=%s", task_id,
                           "sending" if sending else "connecting", type(error).__name__)
            return PublishOutcome.UNKNOWN if sending else PublishOutcome.NOT_SENT
        finally:
            for resource, close in ((connection, "release"), (application, "close")):
                if resource is not None:
                    try:
                        getattr(resource, close)()
                    except Exception as error:
                        logger.warning("task_publish_close_failed reason=%s", type(error).__name__)
