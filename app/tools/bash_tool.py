import subprocess
import platform

SCHEMA = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "执行 Shell 命令并返回输出结果。支持 Windows (PowerShell) 和 Unix (bash) 系统。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                },
                "timeout": {
                    "type": "integer",
                    "description": "命令执行超时时间（秒），默认 60 秒",
                },
            },
            "required": ["command"],
        },
    },
}


async def bash_tool(command: str, timeout: int = 60) -> str:
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
        return output if output.strip() else "(命令执行成功，无输出)"
    except subprocess.TimeoutExpired:
        return f"错误：命令超过 {timeout} 秒超时限制"
    except Exception as e:
        return f"错误：命令执行失败 - {e}"
