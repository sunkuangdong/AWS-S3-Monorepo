import asyncio
from uuid import UUID

from app.clients.openai_image_generation import (
    OpenAIImageGenerationClient,
)
from app.clients.openai_vision import OpenAIVisionClient
from app.clients.s3_storage import S3StorageClient
from app.core.exceptions import (
    ImageGenerationError,
    InvalidObjectKeyError,
    StorageError,
    VisionModelError,
)
from app.models.image_generation import ImageGeneration
from app.repositories.image_generation import ImageGenerationRepository
from app.schemas.image import (
    AnalyzeImageRequest,
    AnalyzeImageResponse,
    PresignUploadRequest,
    PresignUploadResponse,
)
from app.schemas.image_generation import (
    CreateImageGenerationRequest,
    ImageGenerationListResponse,
    ImageGenerationResponse,
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
        image_generation_client: OpenAIImageGenerationClient,
        generation_repository: ImageGenerationRepository,
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
        self.image_generation_client = image_generation_client
        self.generation_repository = generation_repository

    def _build_generation_response(
        self,
        generation: ImageGeneration,
    ) -> ImageGenerationResponse:
        """
        将数据库模型转换为包含临时图片地址的 API 响应。

        Convert a database model into an API response containing
        a temporary image URL.
        """
        output_url: str | None = None

        if generation.output_object_key is not None:
            output_url = (
                self.storage_client.create_presigned_download_url(
                    object_key=generation.output_object_key,
                )
            )

        response = ImageGenerationResponse.model_validate(
            generation
        )

        return response.model_copy(
            update={
                "output_url": output_url,
            }
        )

    @staticmethod
    def _build_edit_prompt(
        *,
        user_prompt: str,
        image_analysis: str,
    ) -> str:
        """
        组合保持参考图主体一致性的编辑提示词。
        Build an editing prompt that preserves reference-subject identity.
        """
        return (
            "Edit the provided reference image. Treat the input image as "
            "the visual source of truth; do not recreate it from scratch.\n\n"
            "Requested edit:\n"
            f"{user_prompt}\n\n"
            "Editing rules:\n"
            "- Follow the user's requested edit as the highest priority.\n"
            "- Attributes explicitly requested by the user may be changed, including "
            "identity, facial features, colors, markings, body proportions, pose, "
            "expression, composition, and camera angle.\n"
            "- Preserve only the attributes and image regions that the user did not "
            "explicitly request to change.\n"
            "- Do not introduce unrelated changes.\n"
            "- Maintain natural edges, lighting, shadows, and color transitions.\n\n"
            "Reference analysis is secondary context only. If it conflicts with "
            "the input image, follow the input image:\n"
            f"{image_analysis}"
        )

    async def create_generation(
        self,
        request: CreateImageGenerationRequest,
    ) -> ImageGenerationResponse:
        """
        创建并执行一次图片生成任务。

        Create and execute one image-generation task.

        执行流程 / Workflow:
            1. 验证可选的参考图 object key
            2. 创建并提交 pending 数据库记录
            3. 可选地分析并下载参考图片
            4. 组合保持主体一致性的编辑提示词
            5. 调用 OpenAI 生成或编辑图片
            6. 在线程中将图片上传到 S3
            7. 更新数据库记录为 completed
            8. 发生外部服务错误时更新为 failed
        """
        input_object_key = request.input_object_key

        if input_object_key is not None:
            self.validate_object_key(
                input_object_key
            )

        generation_type = (
            "image_to_image"
            if input_object_key is not None
            else "text_to_image"
        )

        # 先创建 pending 记录。
        # First create the pending record.

        generation = ImageGeneration(
            user_prompt=request.prompt,
            image_analysis=None,
            final_prompt=request.prompt,
            generation_type=generation_type,
            input_object_key=input_object_key,
            output_object_key=None,
            width=request.width,
            height=request.height,
            status="pending",
        )

        generation = await self.generation_repository.create(
            generation
        )

        # 先提交 pending，使任务在外部调用前持久化。
        # Commit pending before calling external services.
        await self.generation_repository.commit()

        try:
            image_analysis: str | None = None
            final_prompt = request.prompt

            if input_object_key is not None:
                reference_image_url = (
                    self.storage_client.create_presigned_download_url(
                        object_key=input_object_key,
                    )
                )

                image_analysis = await self.vision_client.analyze_image(
                    image_url=reference_image_url,
                    prompt=(
                        "请客观描述这张参考图片中的主体、外观、姿态、"
                        "构图、背景、光线和视觉风格，供后续图片生成使用。"
                    ),
                )

                reference_image = await asyncio.to_thread(
                    self.storage_client.download_image,
                    object_key=input_object_key,
                )

                final_prompt = self._build_edit_prompt(
                    user_prompt=request.prompt,
                    image_analysis=image_analysis,
                )

                image_bytes = await self.image_generation_client.edit_image(
                    image_bytes=reference_image.data,
                    file_name=reference_image.file_name,
                    content_type=reference_image.content_type,
                    prompt=final_prompt,
                    width=request.width,
                    height=request.height,
                )
            else:
                image_bytes = (
                    await self.image_generation_client.generate_image(
                        prompt=final_prompt,
                        width=request.width,
                        height=request.height,
                    )
                )

            # boto3 是同步客户端，放到工作线程中执行。
            # boto3 is synchronous, so run the upload in a worker thread.
            output_object_key = await asyncio.to_thread(
                self.storage_client.upload_generated_image,
                image_bytes=image_bytes,
            )

            generation = (
                await self.generation_repository.mark_completed(
                    generation,
                    image_analysis=image_analysis,
                    final_prompt=final_prompt,
                    output_object_key=output_object_key,
                )
            )
            
            await self.generation_repository.commit()
        except (
            ImageGenerationError,
            StorageError,
            VisionModelError,
        ):
            # 清理当前可能失败的数据库事务。
            # Clear any failed database transaction.
            await self.generation_repository.rollback()

            # pending 已经在前面提交，因此可以重新查询并标记失败。
            # The pending record was committed earlier, so retrieve it
            # again and mark it as failed.
            failed_generation = (
                await self.generation_repository.get_by_id(
                    generation.id
                )
            )

            if failed_generation is not None:
                await self.generation_repository.mark_failed(
                    failed_generation
                )
                await self.generation_repository.commit()

            raise

        return self._build_generation_response(
            generation
        )

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

    async def list_generations(
        self,
        *,
        limit: int,
        offset: int,
    ) -> ImageGenerationListResponse:
        """
        查询图片生成历史记录。

        List image-generation history records.

        记录按照创建时间倒序排列，
        最新创建的记录出现在最前面。
        Records are ordered by creation time in descending order,
        with the newest record first.
        """
        generations = await self.generation_repository.list_recent(
            limit=limit,
            offset=offset,
        )

        items = [
            self._build_generation_response(generation)
            for generation in generations
        ]

        return ImageGenerationListResponse(
            items=items,
            limit=limit,
            offset=offset,
        )

    async def get_generation(
        self,
        generation_id: UUID,
    ) -> ImageGenerationResponse | None:
        """
        根据 UUID 查询图片生成记录。

        Find an image-generation record by UUID.

        找不到记录时返回 None。
        Return None when the record does not exist.
        """
        generation = await self.generation_repository.get_by_id(
            generation_id
        )

        if generation is None:
            return None

        return self._build_generation_response(
            generation
        )
