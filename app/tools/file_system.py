import os
import glob as glob_module
from pathlib import Path


CURRENT_DIR = os.getcwd()

READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取指定文件的内容。支持多种编码自动检测。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要读取的文件路径（绝对路径或相对路径）",
                },
            },
            "required": ["file_path"],
        },
    },
}

WRITE_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "创建新文件并写入内容（仅支持创建新文件，不覆盖已有文件）。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要创建的文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容",
                },
            },
            "required": ["file_path", "content"],
        },
    },
}

EDIT_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "通过精确字符串替换来编辑文件内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要编辑的文件路径",
                },
                "old_string": {
                    "type": "string",
                    "description": "要替换的原始文本（必须精确匹配）",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文本",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
}

LIST_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": "列出指定目录下的所有文件和子目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "要列出的目录路径，默认为当前工作目录",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "是否递归列出子目录",
                },
            },
            "required": [],
        },
    },
}

GLOB_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "glob_files",
        "description": "使用 glob 模式搜索文件（如 **/*.py, src/**/*.ts）。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "文件匹配模式，支持 ** 递归通配符",
                },
            },
            "required": ["pattern"],
        },
    },
}


def _resolve_path(path: str) -> str:
    if not os.path.isabs(path):
        return os.path.join(CURRENT_DIR, path)
    return path


async def read_file_tool(file_path: str) -> str:
    resolved = _resolve_path(file_path)
    if not os.path.exists(resolved):
        return f"错误：文件不存在 - {file_path}"
    if not os.path.isfile(resolved):
        return f"错误：路径不是文件 - {file_path}"

    # Try UTF-8 first, then GBK
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            with open(resolved, "r", encoding=encoding) as f:
                content = f.read()
            if len(content) > 50000:
                content = content[:50000] + "\n...[文件过长，已截断]"
            return content
        except UnicodeDecodeError:
            continue
    return f"错误：无法以支持的编码读取文件 - {file_path}"


async def write_file_tool(file_path: str, content: str) -> str:
    resolved = _resolve_path(file_path)
    if os.path.exists(resolved):
        return f"错误：文件已存在，不允许覆盖 - {file_path}"
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(content)
    return f"文件已创建：{file_path}"


async def edit_file_tool(file_path: str, old_string: str, new_string: str) -> str:
    resolved = _resolve_path(file_path)
    if not os.path.exists(resolved):
        return f"错误：文件不存在 - {file_path}"

    with open(resolved, "r", encoding="utf-8") as f:
        original = f.read()

    if old_string not in original:
        return f"错误：未找到要替换的文本 - {file_path}"

    # Replace first occurrence only
    new_content = original.replace(old_string, new_string, 1)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"文件已编辑：{file_path}"


async def list_files_tool(directory: str = ".", recursive: bool = False) -> str:
    resolved = _resolve_path(directory)
    if not os.path.exists(resolved):
        return f"错误：目录不存在 - {directory}"

    if recursive:
        paths = []
        for root, dirs, files in os.walk(resolved):
            for name in dirs + files:
                paths.append(os.path.join(root, name))
    else:
        paths = [os.path.join(resolved, p) for p in os.listdir(resolved)]

    # Convert to relative paths for readability
    paths = [os.path.relpath(p, CURRENT_DIR) for p in paths]
    paths.sort()
    return "\n".join(paths[:200])


async def glob_files_tool(pattern: str) -> str:
    full_pattern = os.path.join(CURRENT_DIR, pattern)
    matches = glob_module.glob(full_pattern, recursive=True)
    matches = [os.path.relpath(m, CURRENT_DIR) for m in matches]
    matches.sort()
    return "\n".join(matches[:200])
