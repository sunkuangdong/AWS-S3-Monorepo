from openai import AsyncOpenAI, OpenAIError

from app.core.config import Settings
from app.core.exceptions import VisionModelError

class OpenAIVisionClient:
    """
    封装 OpenAI 图片理解功能。

    其他模块只需要调用 analyze_image()，
    不需要了解 OpenAI API 的具体请求格式。
    """
    def __init__(self, settings: Settings) -> None:
        """
        创建 OpenAI 图片理解客户端。

        参数:
            settings: 项目配置对象，包含 API Key 和模型名称。
        """
        self.settings = settings

        # 创建异步 OpenAI 客户端。
        #
        # timeout=60.0 表示请求最多等待 60 秒。
        # 超过 60 秒仍未完成时，SDK 会抛出超时异常。
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=60.0,
        )

    async def analyze_image(
        self,
        image_url: str,
        prompt: str,
    ) -> str:
        """
        调用 OpenAI 视觉模型分析图片。
        参数:
            image_url:
                OpenAI 可以访问的图片 URL。
                当前项目会传入 S3 预签名 URL。
            prompt:
                用户希望模型对图片执行的任务。

        返回:
            OpenAI 生成的图片描述文本。

        异常:
            调用 OpenAI 失败或者没有返回文本时，
            抛出 VisionModelError。
        """
        try:
            response = await self.client.responses.create(
                model=self.settings.openai_vision_model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": prompt,
                            },
                            {
                                "type": "input_image",
                                "image_url": image_url,

                                # low 使用较少的图片 token。
                                # 适合开发测试和普通图片描述。
                                "detail": "low",
                            },
                        ]
                    }
                ],
                max_output_tokens=500,
            )
        except OpenAIError as error:
            # from error 会保留 OpenAI 原始异常，
            # 方便后端日志查看真正原因。
            raise VisionModelError(
                "OpenAI 图片分析请求失败"
            ) from error

        description = response.output_text.strip()

        if not description:
            raise VisionModelError(
                "OpenAI 没有返回图片描述"
            )

        return description


