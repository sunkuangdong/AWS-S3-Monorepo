from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openai_vision import OpenAIVisionClient
from app.clients.s3_storage import S3StorageClient
from app.core.config import get_settings
from app.db.session import get_database_session
from app.repositories.image_generation import ImageGenerationRepository
from app.services.image_service import ImageService

DatabaseSessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]

def get_image_generation_repository(
    session: DatabaseSessionDependency,
) -> ImageGenerationRepository:
    """
    为当前请求创建图片生成 Repository。
    Create an image-generation repository for the current request.

    Repository 使用当前请求的数据库 Session,
    因此不能作为全局单例缓存。
    The repository uses the current request's database session,
    so it must not be cached as a global singleton.
    """
    return ImageGenerationRepository(
        session=session
    )

# 当前请求使用的图片生成 Repository。
# Image-generation repository used by the current request.
ImageGenerationRepositoryDependency = Annotated[
    ImageGenerationRepository,
    Depends(get_image_generation_repository),
]

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

def get_image_service(
    generation_repository: ImageGenerationRepositoryDependency,
) -> ImageService:
    """
    为当前请求创建图片业务服务。
    Create the image service for the current request.

    S3 和 OpenAI 客户端可以长期复用，
    Repository 则跟随当前请求的数据库 Session。
    The S3 and OpenAI clients can be reused, while the repository
    follows the database session of the current request.
    """
    return ImageService(
        storage_client=get_s3_storage_client(),
        vision_client=get_openai_vision_client(),
        generation_repository=generation_repository,
    )
