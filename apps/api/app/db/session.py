from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

# 创建 SQLAlchemy 异步数据库引擎。
# Create the SQLAlchemy asynchronous database engine.
#
# 此处只创建 Engine 对象，不会立即连接 PostgreSQL。
# Creating the Engine object does not connect to PostgreSQL immediately.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

# 创建可复用的异步 Session 工厂。
# Create a reusable asynchronous Session factory.
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_database_session() -> AsyncGenerator[AsyncSession]:
    """
    为一次请求创建并关闭数据库 Session。
    Create and close one database Session for a request.

    yield 返回 Session 后，FastAPI 会把它传给路由或 Service。
    离开 async with 后，Session 会自动关闭。
    FastAPI can inject the yielded Session into a route or service.
    The Session closes automatically when leaving async with.
    """
    async with async_session_factory() as session:
        yield session

async def check_database_connection() -> None:
    """
    执行简单查询，验证 PostgreSQL 是否可以访问。
    Run a simple query to verify PostgreSQL connectivity.
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

async def dispose_database_engine() -> None:
    """
    关闭连接池中的全部数据库连接。
    Close all database connections held by the pool.
    """
    await engine.dispose()

