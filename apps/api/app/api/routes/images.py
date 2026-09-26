import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.core.exceptions import (
    InvalidObjectKeyError,
    StorageError,
    VisionModelError,
)
from app.dependencies import get_image_service
from app.schemas.image import (
    AnalyzeImageRequest,
    AnalyzeImageResponse,
    PresignUploadRequest,
    PresignUploadResponse,
)
from app.services.image_service import ImageService

# 创建当前模块的日志记录器。
# Create a logger for this module.
logger = logging.getLogger(__name__)

# 创建图片模块的路由对象。
# Create the image router.
#
# prefix="/images" 表示这个文件中的接口
# 都会以 /images 开头。
# prefix="/images" adds /images to every endpoint in this module.
router = APIRouter(
    prefix="/images",
    tags=["images"],
)

# 定义 ImageService 的 FastAPI 依赖类型。
# Define the FastAPI dependency type for ImageService.
#
# FastAPI 收到请求时会调用 get_image_service()，
# 然后把返回的 ImageService 传给路由函数。
# FastAPI calls get_image_service() and injects the returned service
# into each route function.
ImageServiceDependency = Annotated[
    ImageService,
    Depends(get_image_service),
]

@router.post(
    "/presign-upload",
    response_model=PresignUploadResponse,
    status_code=status.HTTP_200_OK,
)
def create_presigned_upload(
    request: PresignUploadRequest,
    image_service: ImageServiceDependency,
) -> PresignUploadResponse:
    """
    创建 S3 预签名上传表单。
    Create an S3 presigned upload form.

    请求示例 / Request example:
        {
            "file_name": "dog.jpg",
            "content_type": "image/jpeg"
        }

    该接口只生成临时上传凭证，
    图片不会经过 FastAPI 服务器。
    This endpoint only creates temporary upload credentials;
    the image bytes do not pass through FastAPI.
    """
    try:
        return image_service.create_upload(request)

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except StorageError as error:
        # 把完整错误写进服务器日志。
        # Write the complete exception to the server log.
        logger.exception("生成 S3 预签名上传表单失败")
        # 返回给客户端的信息不包含 AWS 内部细节。
        # Do not expose internal AWS details to the client.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="暂时无法创建图片上传地址",
        ) from error

@router.post(
    "/analyze",
    response_model=AnalyzeImageResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_image(
    request: AnalyzeImageRequest,
    image_service: ImageServiceDependency,
) -> AnalyzeImageResponse:
    """
    使用 OpenAI 分析已经上传到 S3 的图片。
    Analyze an image already uploaded to S3 with OpenAI.

    请求示例 / Request example:
        {
            "object_key": "uploads/abc123.jpg",
            "prompt": "请详细描述这张图片"
        }
    """
    try:
        return await image_service.analyze_image(request)
    except InvalidObjectKeyError as error:
        # object_key 不符合 uploads/ 路径规则。
        # The object key does not satisfy the uploads/ prefix rule.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    except StorageError as error:
        # S3 凭证、权限或者签名过程出错。
        # S3 credentials, permissions, or signing failed.
        logger.exception("生成 S3 图片读取地址失败")

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="暂时无法读取 S3 图片",
        ) from error

    except VisionModelError as error:
        # OpenAI 请求、模型或者余额等问题。
        # The OpenAI request, model, or account balance caused an error.
        logger.exception("OpenAI 图片分析失败")

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenAI 暂时无法分析图片",
        ) from error
