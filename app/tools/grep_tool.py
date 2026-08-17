import re
import os
import subprocess

CURRENT_DIR = os.getcwd()

SCHEMA = {
    "type": "function",
    "function": {
        "name": "grep",
        "description": "使用正则表达式在文件中搜索文本内容。支持 glob 过滤、上下文行、多行模式。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "要搜索的正则表达式模式",
                },
                "path": {
                    "type": "string",
                    "description": "搜索目录或文件路径，默认为当前目录",
                },
                "glob": {
                    "type": "string",
                    "description": "文件名过滤模式（如 *.py, **/*.tsx）",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "匹配行前后显示的行数",
                },
            },
            "required": ["pattern"],
        },
    },
}


async def grep_tool(pattern: str, path: str = ".", glob: str | None = None, context_lines: int = 0) -> str:
    resolved = path if os.path.isabs(path) else os.path.join(CURRENT_DIR, path)

    # Try ripgrep first for performance
    cmd = ["rg", "--no-heading", "-n", "--color", "never"]
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])
    if glob:
        cmd.extend(["-g", glob])
    cmd.append(pattern)
    cmd.append(resolved)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode <= 1:
            output = result.stdout
            if not output:
                return f"未找到匹配模式: {pattern}"
            lines = output.strip().split("\n")
            return "\n".join(lines[:250])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback to Python regex search
    results = []
    if os.path.isfile(resolved):
        files = [resolved]
    else:
        files = []
        for root, _, filenames in os.walk(resolved):
            for fn in filenames:
                if glob and not _match_glob(fn, glob):
                    continue
                files.append(os.path.join(root, fn))

    try:
        compiled = re.compile(pattern, re.MULTILINE | re.DOTALL)
    except re.error as e:
        return f"正则表达式错误: {e}"

    for filepath in files[:100]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines_list = f.readlines()
            for i, line in enumerate(lines_list):
                if compiled.search(line):
                    rel_path = os.path.relpath(filepath, CURRENT_DIR)
                    results.append(f"{rel_path}:{i + 1}: {line.rstrip()}")
                    if len(results) >= 250:
                        break
        except Exception:
            continue
        if len(results) >= 250:
            break

    if not results:
        return f"未找到匹配模式: {pattern}"
    return "\n".join(results)


def _match_glob(filename: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)
