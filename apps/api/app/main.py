import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.router import api_router
from app.core.config import get_settings
from app.core.observability import configure_logging
from app.db.session import (
    check_database_connection,
    dispose_database_engine,
)

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """
    管理 FastAPI 应用生命周期。
    Manage the FastAPI application lifecycle.

    应用关闭时释放数据库连接池。
    Dispose of the database connection pool on shutdown.
    """
    try:
        yield
    finally:
        await dispose_database_engine()

# 创建 FastAPI 应用对象。
# Create the FastAPI application object.
app = FastAPI(
    title="AI Image API",
    version="0.1.0",
    description=(
        "使用 FastAPI、PostgreSQL、Amazon S3 和 OpenAI "
        "构建的 AI 图片生成与管理服务"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    """Attach a request ID and emit one structured access log per request."""
    incoming_request_id = request.headers.get("X-Request-ID", "").strip()
    request_id = (
        incoming_request_id
        if 0 < len(incoming_request_id) <= 128
        else uuid4().hex
    )
    started_at = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.exception(
            "request_failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
            },
        )
        raise

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response

# 把 /api/v1 下的业务路由注册到 FastAPI。
# Register business routes below /api/v1 with FastAPI.
app.include_router(api_router)

@app.get(
    "/health",
    response_model=dict[str, str],
    tags=["system"],
)
def health_check() -> dict[str, str]:
    """
    检查 FastAPI 服务是否正在运行。
    Check whether the FastAPI service is running.

    该接口不会访问 S3，也不会调用 OpenAI。
    This endpoint does not access S3 or call OpenAI.
    """
    return {
        "status": "ok",
    }

@app.get(
    "/health/database",
    response_model=dict[str, str],
    tags=["system"],
)
async def database_health_check() -> dict[str, str]:
    """
    检查 PostgreSQL 是否可以正常连接。
    Check whether PostgreSQL is reachable.
    """
    try:
        await check_database_connection()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库暂时不可用",
        ) from error

    return {
        "status": "ok",
        "database": "reachable",
    }



