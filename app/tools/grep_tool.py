"""Grep 搜索工具"""
import re
import os
import subprocess
from app.tools.base import Tool, ToolResult, ToolUseContext

CURRENT_DIR = os.getcwd()


class GrepTool(Tool):
    name = "grep"
    description = """使用正则表达式在文件中搜索文本内容。

使用场景：按内容搜索代码、查找函数/变量定义、定位错误信息
不适用：按文件名搜索（用 glob_files 工具）
重要：优先使用 ripgrep（rg）以获得更好性能，未安装时回退到 Python 正则
重要：结果最多返回 250 行"""

    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "要搜索的正则表达式模式"},
            "path": {"type": "string", "description": "搜索目录或文件路径，默认为当前目录"},
            "glob": {"type": "string", "description": "文件名过滤模式（如 *.py, **/*.tsx）"},
            "context_lines": {"type": "integer", "description": "匹配行前后显示的行数"},
        },
        "required": ["pattern"],
    }

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        pattern = input["pattern"]
        search_path = input.get("path", ".")
        glob_filter = input.get("glob")
        context_lines = input.get("context_lines", 0)

        resolved = search_path if os.path.isabs(search_path) else os.path.join(context.cwd, search_path)

        # Try ripgrep first
        cmd = ["rg", "--no-heading", "-n", "--color", "never"]
        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])
        if glob_filter:
            cmd.extend(["-g", glob_filter])
        cmd.append(pattern)
        cmd.append(resolved)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode <= 1:
                output = result.stdout
                if not output:
                    return ToolResult(output=f"未找到匹配模式: {pattern}")
                lines = output.strip().split("\n")
                return ToolResult(output="\n".join(lines[:250]))
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
                    if glob_filter and not _match_glob(fn, glob_filter):
                        continue
                    files.append(os.path.join(root, fn))

        try:
            compiled = re.compile(pattern, re.MULTILINE | re.DOTALL)
        except re.error as e:
            return ToolResult(output=f"正则表达式错误: {e}", is_error=True)

        for filepath in files[:100]:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines_list = f.readlines()
                for i, line in enumerate(lines_list):
                    if compiled.search(line):
                        rel_path = os.path.relpath(filepath, context.cwd)
                        results.append(f"{rel_path}:{i + 1}: {line.rstrip()}")
                        if len(results) >= 250:
                            break
            except Exception:
                continue
            if len(results) >= 250:
                break

        if not results:
            return ToolResult(output=f"未找到匹配模式: {pattern}")
        return ToolResult(output="\n".join(results))


def _match_glob(filename: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


# =========================================================
# 向后兼容
# =========================================================

SCHEMA = GrepTool().to_openai_schema()


async def grep_tool(pattern: str, path: str = ".", glob: str | None = None, context_lines: int = 0) -> str:
    tool = GrepTool()
    result = await tool.execute(
        {"pattern": pattern, "path": path, "glob": glob, "context_lines": context_lines},
        ToolUseContext(cwd=CURRENT_DIR),
    )
    return result.output
