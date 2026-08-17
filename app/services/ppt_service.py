from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ppt import AiPptInst, AiPptTemplate


class PptInstService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_conversation_id(self, conversation_id: str) -> AiPptInst | None:
        stmt = select(AiPptInst).where(AiPptInst.conversation_id == conversation_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, inst_id: int) -> AiPptInst | None:
        return await self.db.get(AiPptInst, inst_id)

    async def create(self, inst: AiPptInst) -> AiPptInst:
        self.db.add(inst)
        await self.db.commit()
        await self.db.refresh(inst)
        return inst

    async def update(self, inst: AiPptInst) -> AiPptInst:
        await self.db.merge(inst)
        await self.db.commit()
        return inst

    async def update_status(self, inst_id: int, status: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.status = status
            await self.db.commit()

    async def update_requirement(self, inst_id: int, requirement: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.requirement = requirement
            await self.db.commit()

    async def update_search_info(self, inst_id: int, search_info: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.search_info = search_info
            await self.db.commit()

    async def update_outline(self, inst_id: int, outline: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.outline = outline
            await self.db.commit()

    async def update_template_code(self, inst_id: int, template_code: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.template_code = template_code
            await self.db.commit()

    async def update_schema(self, inst_id: int, ppt_schema: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.ppt_schema = ppt_schema
            await self.db.commit()

    async def update_file_url(self, inst_id: int, file_url: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.file_url = file_url
            await self.db.commit()

    async def update_error(self, inst_id: int, error_msg: str):
        inst = await self.get_by_id(inst_id)
        if inst:
            inst.error_msg = error_msg
            await self.db.commit()

    async def delete_by_conversation_id(self, conversation_id: str) -> int:
        stmt = delete(AiPptInst).where(AiPptInst.conversation_id == conversation_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount


class PptTemplateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_code(self, template_code: str) -> AiPptTemplate | None:
        stmt = select(AiPptTemplate).where(AiPptTemplate.template_code == template_code)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(self) -> list[AiPptTemplate]:
        stmt = select(AiPptTemplate)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_style_tags(self, tags: str) -> list[AiPptTemplate]:
        stmt = select(AiPptTemplate).where(AiPptTemplate.style_tags.contains(tags))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
