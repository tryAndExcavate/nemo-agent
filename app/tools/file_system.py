"""文件系统工具：read_file / write_file / edit_file / list_files / glob_files"""
import os
import glob as glob_module
from pathlib import Path
from app.tools.base import Tool, ToolResult, ToolUseContext

CURRENT_DIR = os.getcwd()


def _resolve_path(path: str) -> str:
    if not os.path.isabs(path):
        return os.path.join(CURRENT_DIR, path)
    return path


# =========================================================
# class-based 工具（供 QueryEngine / Registry 使用）
# =========================================================

class ReadFileTool(Tool):
    name = "read_file"
    description = """读取指定文件的内容。

使用场景：查看文件内容，确认代码、配置、文档等
不适用：编辑文件（用 edit_file 工具）、创建新文件（用 write_file 工具）
重要：支持 UTF-8 / GBK / Latin-1 编码自动检测
重要：大文件（>50000字符）会被截断"""

    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要读取的文件路径（绝对路径或相对路径）",
            },
        },
        "required": ["file_path"],
    }

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        path = os.path.join(context.cwd, input["file_path"])
        if not os.path.exists(path):
            return ToolResult(output=f"错误：文件不存在 - {input['file_path']}", is_error=True)
        if not os.path.isfile(path):
            return ToolResult(output=f"错误：路径不是文件 - {input['file_path']}", is_error=True)

        for encoding in ("utf-8", "gbk", "latin-1"):
            try:
                with open(path, "r", encoding=encoding) as f:
                    content = f.read()
                if len(content) > 50000:
                    content = content[:50000] + "\n...[文件过长，已截断]"
                return ToolResult(output=content)
            except UnicodeDecodeError:
                continue
        return ToolResult(output=f"错误：无法以支持的编码读取文件 - {input['file_path']}", is_error=True)


class WriteFileTool(Tool):
    name = "write_file"
    description = """创建新文件并写入内容。

使用场景：创建尚不存在的文件
不适用：修改已有文件（用 edit_file 工具）、查看文件（用 read_file 工具）
重要：如果文件已存在会拒绝操作，防止误覆盖"""

    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "要创建的文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["file_path", "content"],
    }

    def needs_permission(self, input: dict) -> bool:
        return True

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        path = os.path.join(context.cwd, input["file_path"])
        if os.path.exists(path):
            return ToolResult(output=f"错误：文件已存在，不允许覆盖 - {input['file_path']}", is_error=True)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(input["content"])
        return ToolResult(output=f"文件已创建：{input['file_path']}")


class EditFileTool(Tool):
    name = "edit_file"
    description = """对文件进行精确的字符串替换。

使用场景：修改现有文件的特定内容
不适用：创建新文件（用 write_file 工具）、查看文件（用 read_file 工具）
重要：old_string 必须在文件中唯一存在，否则会失败
重要：必须先用 read_file 工具读取文件，确认 old_string 的确切内容"""

    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "要编辑的文件路径"},
            "old_string": {"type": "string", "description": "要被替换的原始字符串，必须在文件中唯一"},
            "new_string": {"type": "string", "description": "替换后的新字符串"},
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def needs_permission(self, input: dict) -> bool:
        return True

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        path = os.path.join(context.cwd, input["file_path"])
        if not os.path.exists(path):
            return ToolResult(output=f"错误：文件不存在 - {input['file_path']}", is_error=True)

        with open(path, "r", encoding="utf-8") as f:
            original = f.read()

        occurrences = original.count(input["old_string"])
        if occurrences == 0:
            return ToolResult(output="old_string 在文件中未找到", is_error=True)
        if occurrences > 1:
            return ToolResult(
                output=f"old_string 在文件中出现了 {occurrences} 次，必须唯一才能替换",
                is_error=True,
            )

        new_content = original.replace(input["old_string"], input["new_string"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return ToolResult(output=f"文件已编辑：{input['file_path']}")


class ListFilesTool(Tool):
    name = "list_files"
    description = """列出指定目录下的所有文件和子目录。

使用场景：了解项目结构、查找文件位置
不适用：按内容搜索（用 grep 工具）、按模式匹配文件名（用 glob_files 工具）"""

    input_schema = {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "要列出的目录路径，默认为当前工作目录"},
            "recursive": {"type": "boolean", "description": "是否递归列出子目录"},
        },
        "required": [],
    }

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        directory = input.get("directory", ".")
        recursive = input.get("recursive", False)
        resolved = os.path.join(context.cwd, directory)

        if not os.path.exists(resolved):
            return ToolResult(output=f"错误：目录不存在 - {directory}", is_error=True)

        if recursive:
            paths = []
            for root, dirs, files in os.walk(resolved):
                for name in dirs + files:
                    paths.append(os.path.join(root, name))
        else:
            paths = [os.path.join(resolved, p) for p in os.listdir(resolved)]

        paths = [os.path.relpath(p, context.cwd) for p in paths]
        paths.sort()
        return ToolResult(output="\n".join(paths[:200]))


class GlobFilesTool(Tool):
    name = "glob_files"
    description = """使用 glob 模式搜索文件（如 **/*.py, src/**/*.ts）。

使用场景：快速按文件名模式查找文件
不适用：按文件内容搜索（用 grep 工具）、列出目录结构（用 list_files 工具）"""

    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "文件匹配模式，支持 ** 递归通配符"},
        },
        "required": ["pattern"],
    }

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        full_pattern = os.path.join(context.cwd, input["pattern"])
        matches = glob_module.glob(full_pattern, recursive=True)
        matches = [os.path.relpath(m, context.cwd) for m in matches]
        matches.sort()
        return ToolResult(output="\n".join(matches[:200]))


# =========================================================
# 原函数接口（保持向后兼容，现有 agents 仍直接调用）
# =========================================================

READ_FILE_SCHEMA = ReadFileTool().to_openai_schema()
WRITE_FILE_SCHEMA = WriteFileTool().to_openai_schema()
EDIT_FILE_SCHEMA = EditFileTool().to_openai_schema()
LIST_FILES_SCHEMA = ListFilesTool().to_openai_schema()
GLOB_FILES_SCHEMA = GlobFilesTool().to_openai_schema()


async def read_file_tool(file_path: str) -> str:
    tool = ReadFileTool()
    result = await tool.execute({"file_path": file_path}, ToolUseContext(cwd=CURRENT_DIR))
    return result.output


async def write_file_tool(file_path: str, content: str) -> str:
    tool = WriteFileTool()
    result = await tool.execute({"file_path": file_path, "content": content}, ToolUseContext(cwd=CURRENT_DIR))
    return result.output


async def edit_file_tool(file_path: str, old_string: str, new_string: str) -> str:
    tool = EditFileTool()
    result = await tool.execute(
        {"file_path": file_path, "old_string": old_string, "new_string": new_string},
        ToolUseContext(cwd=CURRENT_DIR),
    )
    return result.output


async def list_files_tool(directory: str = ".", recursive: bool = False) -> str:
    tool = ListFilesTool()
    result = await tool.execute({"directory": directory, "recursive": recursive}, ToolUseContext(cwd=CURRENT_DIR))
    return result.output


async def glob_files_tool(pattern: str) -> str:
    tool = GlobFilesTool()
    result = await tool.execute({"pattern": pattern}, ToolUseContext(cwd=CURRENT_DIR))
    return result.output
