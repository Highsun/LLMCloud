"""Fault controls must never be reachable in the normal application."""

from pathlib import Path
import tempfile
import unittest

from starlette.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


class BrowserIsolationTests(unittest.TestCase):
    def test_production_factory_does_not_install_test_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url=""))
            with TestClient(app) as client:
                for method, path in (("POST", "/__test__/fault"), ("GET", "/__test__/audit")):
                    self.assertEqual(client.request(method, path).status_code, 404)
                self.assertFalse(any("__test__" in path for path in client.get("/openapi.json").json()["paths"]))


if __name__ == "__main__":
    unittest.main()
