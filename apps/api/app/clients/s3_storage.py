from dataclasses import dataclass
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


@dataclass(frozen=True)
class StoredImage:
    """
    从 S3 读取的图片内容及其元数据。
    Image content and metadata read from S3.
    """

    data: bytes
    file_name: str
    content_type: str


class S3StorageClient:
    """
    封装项目中所有 Amazon S3 操作。
    Encapsulate all Amazon S3 operations used by the application.

    其他模块不直接调用 boto3，而是通过这个类访问 S3。
    Other modules access S3 through this class instead of calling boto3 directly.
    """

    def __init__(self, settings: Settings) -> None:
        """
        创建 S3StorageClient。
        Create an S3StorageClient.

        参数 / Args:
            settings: 项目配置对象，包含区域、Bucket 和上传限制。
                      Application settings containing the region, bucket,
                      and upload limits.
        """

        self.settings = settings

        # 创建 boto3 S3 客户端。
        # Create the boto3 S3 client.
        #
        # boto3 会自动从以下环境变量读取凭证：
        # boto3 automatically reads credentials from:
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
        Generate a unique S3 object key for a new image.

        参数 / Args:
            file_name: 用户上传的原始文件名。
                       Original file name supplied by the user.
            content_type: 图片的 MIME 类型。
                          Image MIME type.

        返回 / Returns:
            类似 uploads/8c63d49f8d8b4d3f.jpg 的字符串。
            A value such as uploads/8c63d49f8d8b4d3f.jpg.
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
        Generate a presigned POST for direct browser-to-S3 upload.

        该方法不会上传文件，只会生成临时上传凭证。
        This method does not upload a file; it only creates temporary credentials.
        """
        object_key = self.create_object_key(
            file_name=file_name,
            content_type=content_type,
        )

        try:
            # 生成预签名 POST 信息。
            # Generate the presigned POST payload.
            #
            # Fields:
            #   浏览器上传时必须提交的固定字段。
            #   Fixed fields the browser must submit.
            #
            # Conditions:
            #   S3 接收文件时必须检查的限制。
            #   Restrictions that S3 validates before accepting the file.

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
        Generate a temporary read URL for a private S3 object.

        参数 / Args:
            object_key: 图片在 S3 中的路径。
                        Image path in S3.

        返回 / Returns:
            在规定时间内有效的 HTTPS URL。
            An HTTPS URL valid for the configured duration.
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

    def download_image(
        self,
        *,
        object_key: str,
    ) -> StoredImage:
        """
        从私有 S3 Bucket 读取一张参考图。
        Read one reference image from the private S3 bucket.

        返回原始字节和文件元数据，供图片编辑 API 使用。
        Return raw bytes and file metadata for the image editing API.
        """
        try:
            response = self.client.get_object(
                Bucket=self.settings.s3_bucket,
                Key=object_key,
            )

            body = response["Body"]
            try:
                image_bytes = body.read(
                    self.settings.max_upload_bytes + 1
                )
            finally:
                body.close()
        except (
            BotoCoreError,
            ClientError,
            NoCredentialsError,
        ) as error:
            raise StorageError(
                "从 S3 读取参考图失败"
            ) from error

        if not image_bytes:
            raise StorageError(
                "S3 中的参考图内容为空"
            )

        if len(image_bytes) > self.settings.max_upload_bytes:
            raise StorageError(
                "S3 中的参考图超过大小限制"
            )

        content_type = response.get(
            "ContentType",
            "application/octet-stream",
        )

        if content_type not in SUPPORTED_IMAGE_TYPES:
            raise StorageError(
                f"S3 中的参考图格式不受支持：{content_type}"
            )

        return StoredImage(
            data=image_bytes,
            file_name=Path(object_key).name,
            content_type=content_type,
        )

    def upload_generated_image(
        self,
        *,
        image_bytes: bytes,
    ) -> str:
        """
        将生成的 PNG 图片上传到 S3。

        Upload a generated PNG image to S3.

        参数 / Args:
            image_bytes:
                图片的原始二进制内容。
                Raw binary content of the image.

        返回 / Returns:
            图片在 S3 中的 object key。
            Object key of the image in S3.

        异常 / Raises:
            图片内容为空时抛出 ValueError。
            S3 上传失败时抛出 StorageError。
            ValueError for empty image content.
            StorageError when the S3 upload fails.
        """
        if not image_bytes:
            raise ValueError(
                "生成图片内容不能为空"
            )

        object_key = (
            f"generations/{uuid4().hex}.png"
        )

        try:
            self.client.put_object(
                Bucket=self.settings.s3_bucket,
                Key=object_key,
                Body=image_bytes,
                ContentType="image/png",
                ContentLength=len(image_bytes),
            )
        except (
            BotoCoreError,
            ClientError,
            NoCredentialsError,
        ) as error:
            raise StorageError(
                "上传生成图片到 S3 失败"
            ) from error

        return object_key
