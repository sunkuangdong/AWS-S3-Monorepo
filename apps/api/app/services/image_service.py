from app.clients.openai_vision import OpenAIVisionClient
from app.clients.s3_storage import S3StorageClient
from app.core.exceptions import InvalidObjectKeyError
from app.schemas.image import (
    AnalyzeImageRequest,
    AnalyzeImageResponse,
    PresignUploadRequest,
    PresignUploadResponse,
)


class ImageService:
    """
    图片业务服务。
    Application service for image workflows.

    负责组合 S3 和 OpenAI 客户端，完成完整的图片业务流程。
    Combine the S3 and OpenAI clients into complete image workflows.

    路由层不需要了解 / The route layer does not need to know:
    - boto3 如何生成签名
    - OpenAI 请求格式
    - S3 临时 URL 如何生成
    - How boto3 creates signatures
    - The OpenAI request format
    - How temporary S3 URLs are generated
    """

    def __init__(
        self,
        storage_client: S3StorageClient,
        vision_client: OpenAIVisionClient,
    ) -> None:
        """
        创建图片业务服务。
        Create the image application service.

        参数 / Args:
            storage_client:
                负责 S3 上传和读取地址。
                Creates S3 upload and read credentials.

            vision_client:
                负责调用 OpenAI 分析图片。
                Calls OpenAI to analyze images.
        """
        self.storage_client = storage_client
        self.vision_client = vision_client

    def create_upload(
        self,
        request: PresignUploadRequest,
    ) -> PresignUploadResponse:
        """
        根据文件信息创建 S3 预签名上传表单。
        Create an S3 presigned upload form from file metadata.

        参数 / Args:
            request:
                包含原文件名和 Content-Type。
                Contains the original file name and Content-Type.

        返回 / Returns:
            浏览器直传 S3 所需的地址、签名字段和 object_key。
            The URL, signature fields, and object key needed for direct upload.
        """
        return self.storage_client.create_presigned_upload(
            file_name=request.file_name,
            content_type=request.content_type,
        )

    @staticmethod
    def validate_object_key(object_key: str) -> None:
        """
        验证 object_key 是否属于项目允许的目录。
        Validate that an object key belongs to an allowed application prefix.

        当前只允许访问 uploads/ 目录，避免用户要求后端
        为 Bucket 中的其他私有文件生成读取地址。
        Only uploads/ is accepted, preventing callers from requesting read
        URLs for unrelated private objects in the bucket.

        验证成功时不返回数据。
        验证失败时抛出 InvalidObjectKeyError。
        Successful validation returns nothing; invalid input raises
        InvalidObjectKeyError.
        """
        if not object_key.startswith("uploads/"):
            raise InvalidObjectKeyError(
                "此目录不存在"
            )

        if object_key == "uploads/":
            raise InvalidObjectKeyError(
                "object_key 必须指向具体文件"
            )

        if ".." in object_key:
            raise InvalidObjectKeyError(
                "object_key 中不能包含 '..'"
            )


    async def analyze_image(
        self,
        request: AnalyzeImageRequest,
    ) -> AnalyzeImageResponse:
        """
        分析一张已经上传到 S3 的图片。
        Analyze an image already uploaded to S3.

        执行流程 / Workflow:
            1. 验证 object_key 是否安全
            2. 生成 S3 临时读取 URL
            3. 把图片 URL 和 prompt 发送给 OpenAI
            4. 返回图片描述
            1. Validate the object key
            2. Generate a temporary S3 read URL
            3. Send the image URL and prompt to OpenAI
            4. Return the image description
        """
        self.validate_object_key(request.object_key)

        image_url = (
            self.storage_client.create_presigned_download_url(
                object_key=request.object_key,
            )
        )

        description = await self.vision_client.analyze_image(
            image_url=image_url,
            prompt=request.prompt,
        )

        return AnalyzeImageResponse(
            object_key=request.object_key,
            description=description,
        )
