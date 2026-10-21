from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException

from backend.app.api.dataset_openapi import add_dataset_schemas
from backend.app.api.datasets import router as dataset_router
from backend.app.api.errors import http_error_handler, request_validation_handler, service_error_handler
from backend.app.api.middleware import APIErrorMiddleware, RequestIDMiddleware
from backend.app.api.router import router
from backend.app.core.config import Settings, get_settings
from backend.app.core.database import create_database_engine, init_db
from backend.app.services.datasets import DatasetService
from backend.app.services.errors import DatasetServiceError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_database_engine(settings.resolved_database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            settings.ensure_directories()
            init_db(engine)
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=settings.app_name, version="0.1.0",
        description="云端异步大语言模型参数高效微调平台；已实现数据集管理 API。",
        lifespan=lifespan,
        exception_handlers={
            DatasetServiceError: service_error_handler,
            RequestValidationError: request_validation_handler,
            HTTPException: http_error_handler,
        },
    )
    app.state.settings = settings
    app.state.dataset_service = DatasetService(settings, sessions)
    # add_middleware prepends: request context -> CORS -> safe errors -> routes.
    app.add_middleware(APIErrorMiddleware, upload_path=f"{settings.api_prefix}/datasets")
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID", "Location"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(dataset_router, prefix=settings.api_prefix)

    original_openapi = app.openapi

    def openapi():
        if app.openapi_schema is None:
            app.openapi_schema = add_dataset_schemas(original_openapi())
        return app.openapi_schema

    app.openapi = openapi
    return app


app = create_app()
