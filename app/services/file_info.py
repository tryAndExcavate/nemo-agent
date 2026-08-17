from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.file_info import AiFileInfo


class FileInfoService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_file_id(self, file_id: str) -> AiFileInfo | None:
        stmt = select(AiFileInfo).where(AiFileInfo.file_id == file_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, file_info: AiFileInfo) -> AiFileInfo:
        self.db.add(file_info)
        await self.db.commit()
        await self.db.refresh(file_info)
        return file_info

    async def update(self, file_info: AiFileInfo) -> AiFileInfo:
        await self.db.merge(file_info)
        await self.db.commit()
        return file_info

    async def delete_by_file_id(self, file_id: str) -> bool:
        stmt = select(AiFileInfo).where(AiFileInfo.file_id == file_id)
        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            await self.db.delete(record)
            await self.db.commit()
            return True
        return False

    async def delete_by_conversation_id(self, conversation_id: str) -> int:
        stmt = delete(AiFileInfo).where(AiFileInfo.conversation_id == conversation_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def get_all(self) -> list[AiFileInfo]:
        stmt = select(AiFileInfo).order_by(AiFileInfo.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_count(self) -> int:
        stmt = select(func.count()).select_from(AiFileInfo)
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def exists(self, file_id: str) -> bool:
        stmt = select(AiFileInfo.id).where(AiFileInfo.file_id == file_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None
