from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_generation import ImageGeneration


class ImageGenerationRepository:
    """
    图片生成记录的数据访问层。
    Data-access layer for image-generation records.

    负责封装针对 image_generations 表的数据库操作。
    Encapsulate database operations for the image_generations table.
    """
    def __init__(self, session: AsyncSession) -> None:
        """
        创建 Repository。

        Create the repository.

        参数 / Args:
            session:
                当前请求使用的 SQLAlchemy 异步 Session。
                SQLAlchemy asynchronous session for the current request.
        """
        self.session = session

    async def create(
        self,
        generation: ImageGeneration,
    ) -> ImageGeneration:
        """
        新增一条图片生成记录。

        Add one image-generation record.

        此方法只执行 flush, 不执行 commit。
        This method flushes changes but does not commit the transaction.
        """
        self.session.add(generation)

        await self.session.flush()
        await self.session.refresh(generation)

        return generation

    async def mark_completed(
        self,
        generation: ImageGeneration,
        *,
        image_analysis: str | None,
        final_prompt: str,
        output_object_key: str,
    ) -> ImageGeneration:
        """
        将图片生成任务更新为完成状态。

        Mark an image-generation task as completed.
        """
        generation.image_analysis = image_analysis
        generation.final_prompt = final_prompt
        generation.output_object_key = output_object_key
        generation.status = "completed"

        await self.session.flush()
        await self.session.refresh(generation)

        return generation

    async def mark_failed(
        self,
        generation: ImageGeneration,
    ) -> ImageGeneration:
        """
        将图片生成任务更新为失败状态。

        Mark an image-generation task as failed.
        """
        generation.status = "failed"

        await self.session.flush()
        await self.session.refresh(generation)

        return generation

    async def commit(self) -> None:
        """
        提交当前数据库事务。

        Commit the current database transaction.
        """
        await self.session.commit()

    async def rollback(self) -> None:
        """
        回滚当前数据库事务。

        Roll back the current database transaction.
        """
        await self.session.rollback()

    async def get_by_id(
        self,
        generation_id:UUID,
    ) -> ImageGeneration | None:
        """
        根据 UUID 查询单条图片生成记录。

        Find one image-generation record by UUID.
        """
        return await self.session.get(
            ImageGeneration,
            generation_id,
        )

    async def list_recent(
        self,
        *, 
        limit: int = 20,
        offset: int = 0,  
    ) -> list[ImageGeneration]:
        """
        按创建时间倒序查询图片生成记录。

        List image-generation records from newest to oldest.

        参数 / Args:
            limit:
                最多返回多少条记录。
                Maximum number of records to return.

            offset:
                跳过多少条记录，用于分页。
                Number of records to skip for pagination.
        """
        statement = (
            select(ImageGeneration)
            .order_by(ImageGeneration.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.session.scalars(statement)

        return list(result.all())

    async def count_all(self) -> int:
        """
        统计所有图片生成记录的数量。

        Count all image-generation records.
        """
        statement = select(
            func.count()
        ).select_from(
            ImageGeneration
        )

        total = await self.session.scalar(statement)

        return int(total or 0)

