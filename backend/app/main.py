from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.router import router
from backend.app.core.config import get_settings
from backend.app.core.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_directories()
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="云端异步大语言模型参数高效微调平台 · 初始化阶段",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router, prefix=settings.api_prefix)
