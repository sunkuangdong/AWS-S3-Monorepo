import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    HTTPException,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import (
    check_database_connection,
    dispose_database_engine,
)

settings = get_settings()

# 配置项目的基础日志。
# Configure base application logging.
#
# level=logging.INFO:
#     输出 INFO、WARNING、ERROR 等日志。
#     Emit INFO, WARNING, ERROR, and higher-severity records.
#
# format:
#     定义每行日志的显示格式。
#     Define the format of each log line.
logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s: "
        "%(message)s"
    ),
)

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
        "使用 FastAPI、Amazon S3 和 OpenAI "
        "构建的图片理解服务"
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



