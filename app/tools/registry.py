"""工具注册中心 — 构建工具列表供 QueryEngine 使用"""
from __future__ import annotations

from dataclasses import dataclass, field
from app.tools.base import Tool
from app.tools.file_system import ReadFileTool, WriteFileTool, EditFileTool, ListFilesTool, GlobFilesTool
from app.tools.grep_tool import GrepTool
from app.tools.bash_tool import BashTool
from app.tools.skills_tool import LoadSkillTool
from app.tools.file_content import LoadContentTool


@dataclass
class GetToolsOptions:
    enable_bash: bool = True
    enable_file_write: bool = True
    disabled_tools: set[str] = field(default_factory=set)


def get_tools(options: GetToolsOptions | None = None) -> list[Tool]:
    """
    工具列表在会话开始时构建一次，之后通过 to_openai_schema() 转成
    OpenAI function calling 格式传给模型。模型看到的只是 name/description/schema，
    看不到 execute 的具体实现——这一点和原设计完全一致。
    """
    if options is None:
        options = GetToolsOptions()

    tools: list[Tool] = [
        ReadFileTool(),
        EditFileTool(),
        GrepTool(),
        LoadSkillTool(),
        LoadContentTool(),
    ]

    if options.enable_file_write:
        tools.append(WriteFileTool())
    if options.enable_bash:
        tools.append(BashTool())
    tools.append(ListFilesTool())
    tools.append(GlobFilesTool())

    return [t for t in tools if t.name not in options.disabled_tools]
