"""文件内容加载工具 — 对应 Java FileContentService
embed=1: RAG 语义检索（大文件）
embed=0/null: 直接返回文本（小文件）
"""
import logging
from app.tools.base import Tool, ToolResult, ToolUseContext

logger = logging.getLogger(__name__)


class LoadContentTool(Tool):
    name = "loadContent"
    description = """根据文件ID加载文件内容或进行RAG语义检索。

使用场景：用户上传文件后需要查看文件内容或基于文件内容进行问答
不适用：读取本地文件（用 read_file 工具）
重要：如果文件已向量化(embed=1)则使用语义搜索返回相关片段，否则直接返回完整文件内容"""

    input_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "用户的问题，用于语义检索"},
            "fileId": {"type": "string", "description": "文件ID"},
        },
        "required": ["question", "fileId"],
    }

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        # 延迟导入避免循环依赖
        from app.services.file_info import FileInfoService
        from app.services.embedding import embedding_service
        from app.database import async_session_factory

        question = input["question"]
        file_id = input["fileId"]

        logger.info(f"loadContent: fileId={file_id}, question={question}")

        async with async_session_factory() as db:
            file_info_service = FileInfoService(db)
            record = await file_info_service.get_by_file_id(file_id)
            if record is None:
                return ToolResult(output="文件不存在，文件ID: " + file_id, is_error=True)

            if record.status != "SUCCESS":
                return ToolResult(
                    output=f"文件处理中或处理失败，当前状态: {record.status}，文件ID: {file_id}",
                    is_error=True,
                )

            # 已向量化 → RAG 语义检索
            if getattr(record, "embed", None):
                if not question or not question.strip():
                    return ToolResult(output=_build_response(record, "请提供具体问题以进行语义检索。", None))
                segments = await embedding_service.rag_retrieve(file_id, question)
                if not segments:
                    return ToolResult(output=_build_response(record, "未检索到与问题相关的内容", None))
                return ToolResult(output=_build_response(record, "RAG检索", segments))

            # 未向量化 → 直接返回
            text = record.extracted_text or "该文件没有可识别的内容"
            return ToolResult(output=_build_response(record, text, None))


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


# =========================================================
# 向后兼容
# =========================================================

TOOL_SCHEMA = LoadContentTool().to_openai_schema()


async def load_content_tool(db, question: str, fileId: str) -> str:
    """原函数接口，保持向后兼容"""
    tool = LoadContentTool()
    result = await tool.execute(
        {"question": question, "fileId": fileId},
        ToolUseContext(cwd=""),
    )
    return result.output
