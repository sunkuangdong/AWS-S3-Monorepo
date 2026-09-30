from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


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

    limit: int = Field(
        ge=1,
    )

    offset: int = Field(
        ge=0,
    )
