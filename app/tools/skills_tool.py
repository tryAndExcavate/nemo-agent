import os
import yaml
import glob as glob_module

SKILLS_DIR = ""


def set_skills_directory(directory: str):
    global SKILLS_DIR
    SKILLS_DIR = directory


SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": "加载一个专业技能的完整提示词和执行指南。先查看可用技能列表，再调用此工具获取具体技能内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "要加载的技能名称（从可用技能列表中选择）",
                },
            },
            "required": ["skill_name"],
        },
    },
}


def _parse_skill_metadata(filepath: str) -> dict:
    """Parse YAML frontmatter from a SKILL.md file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                frontmatter = content[3:end].strip()
                return yaml.safe_load(frontmatter) or {}
    except Exception:
        pass
    return {}


def list_skills() -> list[dict]:
    """List all available skills with metadata."""
    if not SKILLS_DIR or not os.path.exists(SKILLS_DIR):
        return []

    skills = []
    for filepath in glob_module.glob(os.path.join(SKILLS_DIR, "**/SKILL.md"), recursive=True):
        meta = _parse_skill_metadata(filepath)
        skills.append({
            "name": meta.get("name", os.path.basename(os.path.dirname(filepath))),
            "description": meta.get("description", ""),
            "path": filepath,
        })
    return skills


def get_skill_content(skill_name: str) -> str | None:
    """Get the full content of a skill (without YAML frontmatter)."""
    if not SKILLS_DIR:
        return None

    for filepath in glob_module.glob(os.path.join(SKILLS_DIR, "**/SKILL.md"), recursive=True):
        meta = _parse_skill_metadata(filepath)
        name = meta.get("name", os.path.basename(os.path.dirname(filepath)))
        if name == skill_name:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Strip YAML frontmatter
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        content = content[end + 3:].strip()
                return content
            except Exception:
                return None
    return None


def format_skills_prompt() -> str:
    """Format available skills as a system prompt section."""
    skills = list_skills()
    if not skills:
        return ""

    lines = ["## 可用技能列表", ""]
    for s in skills:
        lines.append(f"- **{s['name']}**: {s['description']}")
    lines.append("")
    lines.append("使用方法：调用 `load_skill` 工具并传入技能名称来获取该技能的完整指南。")
    return "\n".join(lines)


async def load_skill_tool(skill_name: str) -> str:
    content = get_skill_content(skill_name)
    if content is None:
        available = [s["name"] for s in list_skills()]
        return f"未找到技能 '{skill_name}'。可用技能：{', '.join(available)}"
    return content
