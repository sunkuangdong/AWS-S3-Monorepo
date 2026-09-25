from pathlib import Path
from uuid import uuid4

import boto3

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
)

from app.core.config import Settings
from app.core.exceptions import StorageError
from app.schemas.image import PresignUploadResponse

SUPPORTED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

class S3StorageClient:
    """
    封装项目中所有 Amazon S3 操作。

    其他模块不直接调用 boto3，而是通过这个类访问 S3。
    """

    def __init__(self, settings: Settings) -> None:
        """
        创建 S3StorageClient。

        参数:
            settings: 项目配置对象，包含区域、Bucket 和上传限制。
        """

        self.settings = settings

        # 创建 boto3 的 S3 客户端。
        #
        # boto3 会自动从环境变量读取：
        # AWS_ACCESS_KEY_ID
        # AWS_SECRET_ACCESS_KEY

        self.client = boto3.client(
            "s3",
            region_name=settings.aws_region,
        )

    def create_object_key(
        self,
        file_name: str,
        content_type: str,
    ) -> str:
        """
        为新图片生成唯一的 S3 object key。

        参数:
            file_name: 用户上传的原始文件名。
            content_type: 图片的 MIME 类型。

        返回:
            类似 uploads/8c63d49f8d8b4d3f.jpg 的字符串。
        """
        if content_type not in SUPPORTED_IMAGE_TYPES:
            raise ValueError(f"不支持的图片格式：{content_type}")

        original_suffix = Path(file_name).suffix.lower()
        expected_suffix=SUPPORTED_IMAGE_TYPES[content_type]

        if (
            content_type == "image/jpeg"
            and original_suffix in {".jpg", ".jpeg"}
        ):
            final_suffix = original_suffix
        else:
            final_suffix = expected_suffix

        unique_file_name = uuid4().hex

        return f"uploads/{unique_file_name}{final_suffix}"

    def create_presigned_upload(
        self,
        file_name: str,
        content_type: str,
    ) -> PresignUploadResponse:
        """
        生成浏览器直传 S3 使用的预签名 POST 表单。

        该方法不会上传文件，只会生成临时上传凭证。
        """
        object_key = self.create_object_key(
            file_name=file_name,
            content_type=content_type,
        )

        try:
            # 生成预签名 POST 信息。
            #
            # Fields:
            #   浏览器上传时必须提交的固定字段。
            #
            # Conditions:
            #   S3 接收文件时必须检查的限制。

            result = self.client.generate_presigned_post(
                Bucket=self.settings.s3_bucket,
                Key=object_key,
                Fields={
                    "Content-Type": content_type,
                },
                Conditions=[
                    {
                        "Content-Type": content_type,
                    },
                    [
                        "content-length-range",
                        1,
                        self.settings.max_upload_bytes,
                    ],
                ],
                ExpiresIn=self.settings.presigned_url_expires,
            )
        except (
            BotoCoreError,
            ClientError,
            NoCredentialsError,
        ) as error:
            raise StorageError(
                "生成 S3 预签名上传表单失败"
            ) from error

        return PresignUploadResponse(
            upload_url=result["url"],
            fields=result["fields"],
            object_key=object_key,
            expires_in=self.settings.presigned_url_expires,
        )

    def create_presigned_download_url(
        self,
        object_key: str,
    ) -> str:
        """
        为私有 S3 对象生成临时读取地址。

        参数:
            object_key: 图片在 S3 中的路径。

        返回:
            在规定时间内有效的 HTTPS URL。
        """

        try:
            return self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": self.settings.s3_bucket,
                    "Key": object_key,
                },
                ExpiresIn=self.settings.presigned_url_expires,
            )
        except (
            BotoCoreError,
            ClientError,
            NoCredentialsError,
        ) as error:
            raise StorageError(
                "生成 S3 预签名读取地址失败"
            ) from error
