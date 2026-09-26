from functools import lru_cache

from app.clients.openai_vision import OpenAIVisionClient
from app.clients.s3_storage import S3StorageClient
from app.core.config import get_settings
from app.services.image_service import ImageService


@lru_cache(maxsize=1)
def get_s3_storage_client() -> S3StorageClient:
    """
    创建并缓存 S3 客户端。
    Create and cache the S3 client.

    第一次调用时 / On the first call:
        1. 获取 Settings
        2. 创建 S3StorageClient
        3. 把客户端缓存在当前 Python 进程内
        1. Load Settings
        2. Create S3StorageClient
        3. Cache the client in the current Python process

    后续调用直接返回同一个 S3StorageClient。
    Later calls return the same S3StorageClient instance.
    """
    return S3StorageClient(
        settings=get_settings(),
    )

@lru_cache(maxsize=1)
def get_openai_vision_client() -> OpenAIVisionClient:
    """
    创建并缓存 OpenAI 图片理解客户端。
    Create and cache the OpenAI vision client.

    应用运行期间复用同一个客户端，
    避免每个 HTTP 请求都创建新的网络客户端。
    Reuse one client during the process lifetime instead of creating
    a new network client for every HTTP request.
    """
    return OpenAIVisionClient(
        settings=get_settings()
    )

@lru_cache(maxsize=1)
def get_image_service() -> ImageService:
    """
    创建并缓存图片业务服务。
    Create and cache the image application service.

    将 S3 客户端和 OpenAI 客户端注入 ImageService。
    Inject the S3 and OpenAI clients into ImageService.
    """
    return ImageService(
        storage_client=get_s3_storage_client(),
        vision_client=get_openai_vision_client(),
    )
