"""Publisher boundaries against injected clients; real Redis is checked separately."""

import unittest
from pathlib import Path
import subprocess
import sys
import socket
import threading
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

from backend.app.core.config import Settings
from backend.app.core.task_contract import PublishOutcome
from backend.app.services.task_dispatch import CeleryPublisher


class TaskDispatchTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(_env_file=None, redis_url="redis://127.0.0.1:6379/0", training_queue="test-gpu")
        self.publisher = CeleryPublisher(self.settings)

    def test_success_has_one_attempt_stable_name_ids_timeout_and_no_retries(self):
        task, message = uuid4(), uuid4()
        with patch("kombu.Connection") as connect, patch("kombu.Producer") as producer, patch("celery.Celery") as app:
            result = self.publisher.publish(task, message)
        self.assertEqual(result, PublishOutcome.ACCEPTED)
        connect.return_value.ensure_connection.assert_called_once_with(max_retries=0)
        options = connect.call_args.kwargs["transport_options"]
        self.assertEqual(options["socket_connect_timeout"], 1.0)
        self.assertEqual(options["socket_timeout"], 1.0)
        self.assertFalse(options["retry_on_timeout"])
        retry = connect.return_value.default_channel.client.set_retry.call_args.args[0]
        self.assertEqual(retry._retries, 0)
        app.return_value.send_task.assert_called_once_with("worker.train", args=[str(task)], task_id=str(message),
            producer=producer.return_value, queue="test-gpu", serializer="json", retry=False,
            ignore_result=True, add_to_parent=False)
        connect.return_value.release.assert_called_once()
        app.return_value.close.assert_called_once()

    def test_connection_failure_is_definitely_not_sent_without_a_publish_call(self):
        with patch("kombu.Connection") as connect, patch("celery.Celery") as app:
            connect.return_value.ensure_connection.side_effect = OSError("private broker credentials")
            with self.assertLogs("backend.app.services.task_dispatch", level="WARNING") as logs:
                result = self.publisher.publish(uuid4(), uuid4())
        self.assertEqual(result, PublishOutcome.NOT_SENT)
        app.assert_not_called()
        connect.return_value.release.assert_called_once()
        self.assertNotIn("private broker credentials", " ".join(logs.output))

    def test_sending_failure_is_unknown_not_definite_failure_and_never_retried(self):
        with patch("kombu.Connection"), patch("kombu.Producer"), patch("celery.Celery") as app:
            app.return_value.send_task.side_effect = OSError("ack lost")
            self.assertEqual(self.publisher.publish(uuid4(), uuid4()), PublishOutcome.UNKNOWN)
            app.return_value.send_task.assert_called_once()

    def test_cleanup_failure_does_not_erase_a_confirmed_publish(self):
        with patch("kombu.Connection") as connect, patch("kombu.Producer"), patch("celery.Celery") as app:
            connect.return_value.release.side_effect = OSError()
            app.return_value.close.side_effect = OSError()
            self.assertEqual(self.publisher.publish(uuid4(), uuid4()), PublishOutcome.ACCEPTED)

    def test_unsupported_transport_or_failover_url_never_attempts_network(self):
        for url in ("amqp://127.0.0.1", "redis://host1;redis://host2"):
            with self.subTest(url=url), patch("kombu.Connection") as connect:
                publisher = CeleryPublisher(Settings(_env_file=None, redis_url=url))
                self.assertEqual(publisher.publish(uuid4(), uuid4()), PublishOutcome.NOT_SENT)
                connect.assert_not_called()

    def test_api_cold_import_does_not_import_worker_trainer_or_transport(self):
        code = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'worker', 'torch', 'numpy', 'transformers', 'datasets',
                'peft', 'trl', 'accelerate', 'huggingface_hub', 'celery', 'kombu', 'redis'} or fullname == 'trainer.train':
            raise AssertionError('Unexpected import: ' + fullname)
sys.meta_path.insert(0, Block())
from backend.app.main import create_app
assert '/api/v1/tasks' in create_app().openapi()['paths']
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_socket_timeout_is_bounded_and_does_not_reconnect(self):
        stopped, accepted = threading.Event(), []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(0.1)
            port = listener.getsockname()[1]
            def blackhole():
                while not stopped.is_set():
                    try:
                        connection, _address = listener.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    accepted.append(connection)
                for connection in accepted:
                    connection.close()
            thread = threading.Thread(target=blackhole)
            thread.start()
            try:
                publisher = CeleryPublisher(Settings(_env_file=None,
                    redis_url=f"redis://127.0.0.1:{port}/0", task_publish_timeout_seconds=0.1))
                started = time.monotonic()
                self.assertEqual(publisher.publish(uuid4(), uuid4()), PublishOutcome.NOT_SENT)
                self.assertLess(time.monotonic() - started, 3)
                self.assertEqual(len(accepted), 1)
            finally:
                stopped.set()
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
