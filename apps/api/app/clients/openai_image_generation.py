import base64
import binascii

from openai import AsyncOpenAI, OpenAIError

from app.core.config import Settings
from app.core.exceptions import ImageGenerationError


class OpenAIImageGenerationClient:
    """
    封装 OpenAI 图片生成功能。
    Encapsulate OpenAI image-generation operations.

    其他模块只接收最终图片字节，
    不需要了解 OpenAI 响应和 Base64 解码细节。
    Other modules receive the final image bytes without needing
    to understand OpenAI responses or Base64 decoding.
    """
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        """
        创建 OpenAI 图片生成客户端。
        Create the OpenAI image-generation client.
        """
        self.settings = settings

        # 图片生成通常比文本请求耗时更长。
        # Image generation usually takes longer than text requests.
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=180.0,
        )

    async def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        """
        根据提示词生成一张 PNG 图片。

        Generate one PNG image from a prompt.

        参数 / Args:
            prompt:
                发送给图片生成模型的最终提示词。
                Final prompt sent to the image-generation model.

            width:
                图片宽度。
                Image width.

            height:
                图片高度。
                Image height.

        返回 / Returns:
            解码后的 PNG 图片字节。
            Decoded PNG image bytes.

        异常 / Raises:
            OpenAI 请求失败、响应为空或 Base64 无法解码时，
            抛出 ImageGenerationError。
            ImageGenerationError when the request fails, returns no image,
            or contains invalid Base64 data.
        """
        size = f"{width}x{height}"
        try:
            response = await self.client.images.generate(
                model=self.settings.image_generation_model,
                prompt=prompt,
                n=1,
                size=size,
                output_format="png",
            )
        except OpenAIError as error:
            raise ImageGenerationError(
                "OpenAI 图片生成请求失败"
            ) from error

        if not response.data:
            raise ImageGenerationError(
                "OpenAI 没有返回图片数据"
            )

        encoded_image = response.data[0].b64_json

        if not encoded_image:
            raise ImageGenerationError(
                "OpenAI 返回的图片内容为空"
            )

        try:
            return base64.b64decode(
                encoded_image,
                validate=True,
            )
        except binascii.Error as error:
            raise ImageGenerationError(
                "OpenAI 返回的图片数据无法解码"
            ) from error
