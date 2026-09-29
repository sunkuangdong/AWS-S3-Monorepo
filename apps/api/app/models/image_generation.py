from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base

class ImageGeneration(Base):
    """
    保存一次图片生成任务及其结果。
    Store one image-generation task and its result.
    """
    __tablename__ = "image_generations"

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )

    # 用户最初输入的生成要求。
    # Original generation request supplied by the user.
    user_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # 参考图片的分析结果；纯文字生成时为空。
    # Analysis of the reference image; null for text-only generation.
    image_analysis: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # 实际发送给图片生成模型的最终提示词。
    # Final prompt sent to the image-generation model.
    final_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # text_to_image 或 image_to_image。
    # Either text_to_image or image_to_image.
    generation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    # 用户上传的参考图 S3 object key。
    # S3 object key of the optional reference image.
    input_object_key: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    # 生成结果的 S3 object key。
    # S3 object key of the generated image.
    output_object_key: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    width: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    height: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # pending、completed 或 failed。
    # One of pending, completed, or failed.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

