import logging

from fastapi import FastAPI

from app.api.router import api_router

from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()

# 配置项目的基础日志。
#
# level=logging.INFO:
#     输出 INFO、WARNING、ERROR 等日志。
#
# format:
#     定义每行日志的显示格式。
logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s: "
        "%(message)s"
    ),
)

# 创建 FastAPI 应用对象。
app = FastAPI(
    title="AI Image API",
    version="0.1.0",
    description=(
        "使用 FastAPI、Amazon S3 和 OpenAI "
        "构建的图片理解服务"
    ),
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
app.include_router(api_router)

@app.get(
    "/health",
    response_model=dict[str, str],
    tags=["system"],
)
def health_check() -> dict[str, str]:
    """
    检查 FastAPI 服务是否正在运行。

    该接口不会访问 S3，也不会调用 OpenAI。
    """
    return {
        "status": "ok",
    }

