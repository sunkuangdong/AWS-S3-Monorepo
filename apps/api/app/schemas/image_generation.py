from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class CreateImageGenerationRequest(BaseModel):
    """
    创建图片生成任务时接收的数据。

    Data accepted when creating an image-generation task.
    """
    prompt: str = Field(
        min_length=1,
        max_length=400,
        description=(
            "用户输入的图片生成要求 / "
            "Image-generation request supplied by the user"
        ),
    )

    input_object_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
        description=(
            "可选的参考图片 S3 object key / "
            "Optional S3 object key of the reference image"
        ),
    )

    # 第一版只开放已经验证过的 1024×1024。
    # The first version only exposes the verified 1024×1024 size.
    width: Literal[1024] = 1024
    height: Literal[1024] = 1024

class ImageGenerationResponse(BaseModel):
    """
    返回给前端的图片生成记录。

    Image-generation record returned to the frontend.
    """

    # 允许 Pydantic 从 SQLAlchemy ORM 对象读取属性。
    # Allow Pydantic to read attributes from SQLAlchemy ORM objects.
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID

    user_prompt: str

    image_analysis: str | None

    final_prompt: str

    generation_type: Literal[
        "text_to_image",
        "image_to_image",
    ]

    input_object_key: str | None

    output_object_key: str | None

    output_url: str | None = Field(
        default=None,
        description=(
            "生成图片的临时访问地址 / "
            "Temporary URL for accessing the generated image"
        ),
    )

    width: int = Field(
        gt=0,
    )

    height: int = Field(
        gt=0,
    )

    status: Literal[
        "pending",
        "completed",
        "failed",
    ]

    created_at: datetime


class ImageGenerationListResponse(BaseModel):
    """
    图片生成历史列表响应。

    Response containing a list of image-generation records.
    """
    items: list[ImageGenerationResponse]

    total: int = Field(
        ge=0,
        description=(
            "图片生成记录总数 / "
            "Total number of image-generation records"
        ),
    )

    limit: int = Field(
        ge=1,
    )

    offset: int = Field(
        ge=0,
    )
