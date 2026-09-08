"""Bash 命令执行工具"""
import os
import subprocess
import platform
from app.tools.base import Tool, ToolResult, ToolUseContext

CURRENT_DIR = os.getcwd()


class BashTool(Tool):
    name = "bash"
    description = """执行 Shell 命令并返回输出结果。

使用场景：运行构建命令、安装依赖、执行脚本、查看系统信息
不适用：搜索文件内容（用 grep 工具）、读取文件（用 read_file 工具）
重要：Windows 使用 PowerShell，Unix 使用 bash
重要：默认超时 60 秒，输出超过 10000 字符会被截断"""

    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "timeout": {"type": "integer", "description": "命令执行超时时间（秒），默认 60 秒"},
        },
        "required": ["command"],
    }

    def needs_permission(self, input: dict) -> bool:
        return True

    async def execute(self, input: dict, context: ToolUseContext) -> ToolResult:
        command = input["command"]
        timeout = input.get("timeout", 60)
        is_windows = platform.system() == "Windows"
        shell_cmd = ["powershell.exe", "-Command", command] if is_windows else ["bash", "-c", command]

        try:
            result = subprocess.run(
                shell_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            output = result.stdout
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr

            if len(output) > 10000:
                output = output[:10000] + "\n...[输出过长，已截断]"
            return ToolResult(output=output if output.strip() else "(命令执行成功，无输出)")
        except subprocess.TimeoutExpired:
            return ToolResult(output=f"错误：命令超过 {timeout} 秒超时限制", is_error=True)
        except Exception as e:
            return ToolResult(output=f"错误：命令执行失败 - {e}", is_error=True)


# =========================================================
# 向后兼容
# =========================================================

SCHEMA = BashTool().to_openai_schema()


async def bash_tool(command: str, timeout: int = 60) -> str:
    tool = BashTool()
    result = await tool.execute(
        {"command": command, "timeout": timeout},
        ToolUseContext(cwd=CURRENT_DIR),
    )
    return result.output
