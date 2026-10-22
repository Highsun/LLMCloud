"""Opt-in fault injection for serve_test_api only; never imported by production."""

import errno
from threading import Lock
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import OperationalError

from backend.app.services.datasets import DatasetService


class FaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["storage", "database", "internal", "list_database", "none"]


def unavailable_session():
    raise OperationalError("injected test database failure", {}, Exception("test only"))


class FaultDatasetService(DatasetService):
    def __init__(self, original: DatasetService):
        super().__init__(original.settings, original.session_factory)
        self._fault = "none"
        self._lock = Lock()

    def set_fault(self, mode: str):
        with self._lock:
            self._fault = mode

    def take_fault(self, *, listing=False):
        with self._lock:
            if (self._fault == "list_database") != listing:
                return "none"
            mode, self._fault = self._fault, "none"
            return mode

    def create(self, source, *, filename, name=None):
        mode = self.take_fault()
        if mode == "internal":
            raise RuntimeError("injected test failure, must not reach the response")
        service = DatasetService(self.settings, unavailable_session if mode == "database" else self.session_factory)
        if mode == "storage":
            def unavailable_directory():
                raise OSError(errno.ENOSPC, "injected test disk full")
            service._directories = unavailable_directory
        return service.create(source, filename=filename, name=name)

    def list(self, query=None):
        if self.take_fault(listing=True) == "list_database":
            return DatasetService(self.settings, unavailable_session).list(query)
        return super().list(query)


def install_test_controls(app: FastAPI) -> None:
    service = FaultDatasetService(app.state.dataset_service)
    app.state.dataset_service = service

    @app.post("/__test__/fault", include_in_schema=False)
    def set_fault(request: FaultRequest):
        service.set_fault(request.mode)
        return {"mode": request.mode}

    @app.get("/__test__/audit", include_in_schema=False)
    def audit():
        return service.audit_storage(verify_hash=True)
