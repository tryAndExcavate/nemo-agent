"""
文件管理服务 — 上传、解析、图片识别、大文件向量化
对应 Java FileManageService
"""
import base64
import uuid
import logging
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models.file_info import AiFileInfo
from app.models.schemas import FileInfo
from app.services.file_info import FileInfoService
from app.services.file_parser import FileParserService
from app.services.minio_client import minio_service, generate_object_name
from app.services.embedding import embedding_service

logger = logging.getLogger(__name__)


class FileManageService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_info_service = FileInfoService(db)
        self.parser = FileParserService()

    async def upload_file(self, file_content: bytes, filename: str, content_type: str = "application/octet-stream") -> FileInfo:
        file_id = str(uuid.uuid4()).replace("-", "")
        file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
        file_size = len(file_content)

        logger.info(f"开始处理文件上传: fileId={file_id}, fileName={filename}, fileType={file_type}, size={file_size}")

        # 1. 保存记录（状态 PROCESSING）
        db_record = AiFileInfo(
            file_id=file_id, file_name=filename, file_type=file_type,
            file_size=file_size, status="PROCESSING",
        )
        db_record = await self.file_info_service.save(db_record)

        # 2. 上传 MinIO（异步执行，失败不阻塞）
        object_name = generate_object_name(file_id, file_type)
        try:
            minio_service.upload_file(object_name, file_content, content_type)
        except Exception as e:
            logger.warning(f"MinIO 上传失败，跳过: {e}")

        # 3. 按类型处理
        logger.info(f"文件类型判断: file_type={file_type}, is_image={self._is_image_file(file_type)}, is_text={self._is_text_file(file_type)}")
        extracted_text = ""
        if self._is_image_file(file_type):
            # 图片：多模态 VL 模型识别
            extracted_text = await self._image_to_text(file_content, file_type)
            logger.info(f"图片识别完成: fileId={file_id}, 文本长度={len(extracted_text)}")

        elif self._is_text_file(file_type):
            # 文档：解析为纯文本
            extracted_text = self.parser.parse(file_content, file_type)
            logger.info(f"文件解析完成: fileId={file_id}, 文本长度={len(extracted_text)}")

            # 大文件自动向量化
            if embedding_service.is_large_file(extracted_text):
                logger.info(f"检测到大文件，开始向量化: fileId={file_id}")
                try:
                    await embedding_service.process_large_file(file_id, extracted_text)
                    db_record.embed = True
                except Exception as e:
                    logger.error(f"大文件向量化失败: fileId={file_id}, {e}")

        # 4. 更新状态
        db_record.minio_path = object_name
        db_record.extracted_text = extracted_text
        db_record.status = "SUCCESS"
        await self.file_info_service.update(db_record)

        return FileInfo(
            file_id=file_id, file_name=filename, file_type=file_type,
            file_size=file_size, minio_path=object_name,
            extracted_text=extracted_text, status="SUCCESS",
        )

    async def get_file_info(self, file_id: str) -> FileInfo | None:
        record = await self.file_info_service.get_by_file_id(file_id)
        if record is None:
            return None
        return FileInfo(
            file_id=record.file_id, file_name=record.file_name,
            file_type=record.file_type, file_size=record.file_size,
            minio_path=record.minio_path, extracted_text=record.extracted_text,
            status=record.status, conversation_id=record.conversation_id,
        )

    async def get_file_content(self, file_id: str) -> str:
        record = await self.file_info_service.get_by_file_id(file_id)
        if record is None:
            raise ValueError("文件不存在")
        if record.extracted_text:
            return record.extracted_text
        if record.minio_path:
            content = minio_service.download_file(record.minio_path)
            return self.parser.parse(content, record.file_type or "txt")
        return ""

    async def delete_file(self, file_id: str):
        record = await self.file_info_service.get_by_file_id(file_id)
        if record and record.minio_path:
            try:
                minio_service.delete_file(record.minio_path)
            except Exception:
                pass
        embedding_service.delete_collection(file_id)
        await self.file_info_service.delete_by_file_id(file_id)

    async def get_all_files(self) -> list[FileInfo]:
        records = await self.file_info_service.get_all()
        return [
            FileInfo(
                file_id=r.file_id, file_name=r.file_name, file_type=r.file_type,
                file_size=r.file_size, minio_path=r.minio_path,
                extracted_text=r.extracted_text, status=r.status,
                conversation_id=r.conversation_id,
            )
            for r in records
        ]

    async def get_file_count(self) -> int:
        return await self.file_info_service.get_count()

    async def exists(self, file_id: str) -> bool:
        return await self.file_info_service.exists(file_id)

    # ========= 图片识别（多模态） =========
    async def _image_to_text(self, image_bytes: bytes, file_type: str) -> str:
        """对应 Java image2Text(): 调用 VL 模型将图片转换为文字描述"""

        mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp"}
        mime = mime_map.get(file_type, "image/png")
        data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"

        # VL 模型走 DashScope（兼容 OpenAI 协议）
        vl_client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        response = await vl_client.chat.completions.create(
            model="qwen3.7-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": "请描述这张图片的内容，包括场景、对象、布局、颜色、文字信息，直接输出纯文本描述，不要多余说明，不要增加任何特殊符号，特别是换行符"},
                ],
            }],
            temperature=0.2,
        )

        text = response.choices[0].message.content or "[无法识别图片内容]"
        return text.strip()

    @staticmethod
    def _is_text_file(file_type: str) -> bool:
        return file_type.lower() in ("pdf", "docx", "doc", "txt")

    @staticmethod
    def _is_image_file(file_type: str) -> bool:
        return file_type.lower() in ("jpg", "jpeg", "png", "gif", "bmp")
