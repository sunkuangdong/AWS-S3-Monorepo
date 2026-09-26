import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 当前文件：apps/api/app/core/config.py
# Current file: apps/api/app/core/config.py
# parents[0] = core, parents[1] = app, parents[2] = api
API_ROOT = Path(__file__).resolve().parents[2]
# 后端环境文件：apps/api/.env
# Backend environment file: apps/api/.env
ENV_FILE = API_ROOT / ".env"

load_dotenv(ENV_FILE)

def require_environment_variable(name:str) -> str:
    """
    读取一个必需的环境变量。
    Read a required environment variable.

    参数 / Args:
        name: 环境变量名称，例如 OPENAI_API_KEY。
              Environment variable name, for example OPENAI_API_KEY.

    返回 / Returns:
        去除两端空格后的环境变量值。
        The environment variable value with surrounding whitespace removed.

    异常 / Raises:
        如果环境变量不存在或内容为空，抛出 RuntimeError。
        RuntimeError if the variable is missing or empty.
    """
    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(f"缺少必需的环境变量：{name}")

    return value.strip()

@dataclass(frozen=True)
class Settings:
    """
    保存 FastAPI 后端使用的全部配置。
    Store all configuration used by the FastAPI backend.

    frozen=True 表示对象创建后不能再修改，
    可以防止程序运行期间意外改变 Bucket 或模型名称。
    frozen=True prevents accidental changes to the bucket or model
    configuration while the process is running.
    """
    aws_region:str
    s3_bucket: str
    openai_api_key: str
    openai_vision_model: str
    presigned_url_expires: int
    max_upload_bytes: int

    frontend_origin: str

@lru_cache
def get_settings() -> Settings:
    """
    创建并缓存配置对象。
    Create and cache the application settings object.

    第一次调用时读取环境变量并创建 Settings。
    后续调用会直接返回同一个 Settings 对象。
    The first call reads environment variables and creates Settings.
    Later calls return the same in-memory object.
    """

    return Settings(
        aws_region=require_environment_variable(
            "AWS_DEFAULT_REGION"
        ),
        s3_bucket=require_environment_variable(
            "S3_BUCKET"
        ),
        openai_api_key=require_environment_variable(
            "OPENAI_API_KEY"
        ),
        openai_vision_model=require_environment_variable(
            "MODEL_NAME"
        ),
        # 默认有效期为 10 分钟。
        # Default expiration time: 10 minutes.
        presigned_url_expires=int(
            os.getenv("S3_PRESIGNED_URL_EXPIRES", "600")
        ),
        # 默认最大上传大小为 10 MiB。
        # Default maximum upload size: 10 MiB.
        max_upload_bytes=int(
            os.getenv(
                "MAX_UPLOAD_BYTES",
                str(10 * 1024 * 1024),
            )
        ),
        frontend_origin=os.getenv(
            "FRONTEND_ORIGIN",
            "http://localhost:5173",
        ),
    )


