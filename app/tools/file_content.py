"""
文件内容加载工具 — 对应 Java FileContentService
embed=1: RAG 语义检索（大文件）
embed=0/null: 直接返回文本（小文件）
"""
import logging
from app.services.file_info import FileInfoService
from app.services.embedding import embedding_service

logger = logging.getLogger(__name__)

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "loadContent",
        "description": "根据文件ID加载文件内容或进行RAG语义检索。如果文件已向量化(embed=1)则使用语义搜索返回相关片段，否则直接返回完整文件内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "用户的问题，用于语义检索",
                },
                "fileId": {
                    "type": "string",
                    "description": "文件ID",
                },
            },
            "required": ["question", "fileId"],
        },
    },
}


async def load_content_tool(db, question: str, fileId: str) -> str:
    """根据 embed 标记选择 RAG 或直接返回"""
    logger.info(f"loadContent: fileId={fileId}, question={question}")

    file_info_service = FileInfoService(db)
    record = await file_info_service.get_by_file_id(fileId)
    if record is None:
        return "文件不存在，文件ID: " + fileId

    if record.status != "SUCCESS":
        return f"文件处理中或处理失败，当前状态: {record.status}，文件ID: {fileId}"

    # 已向量化 → RAG 语义检索
    if getattr(record, "embed", None):
        return await _retrieve_with_rag(fileId, record, question)

    # 未向量化 → 直接返回
    return _load_directly(fileId, record)


async def _retrieve_with_rag(file_id: str, record, question: str) -> str:
    if not question or not question.strip():
        return _build_response(record, "请提供具体问题以进行语义检索。", None)

    segments = await embedding_service.rag_retrieve(file_id, question)

    if not segments:
        return _build_response(record, "未检索到与问题相关的内容", None)

    return _build_response(record, "RAG检索", segments)


def _load_directly(file_id: str, record) -> str:
    text = record.extracted_text or "该文件没有可识别的内容"
    return _build_response(record, text, None)


def _build_response(record, content: str, segments: list[str] | None) -> str:
    parts = [
        "=== 文件信息 ===",
        f"文件名: {record.file_name}",
        f"文件类型: {record.file_type}",
        "",
        "=== 文件内容 ===",
        "",
    ]
    if segments:
        parts.append("相关内容:\n")
        for s in segments:
            parts.append(s)
            parts.append("")
    elif content:
        parts.append(content)
    return "\n".join(parts)
