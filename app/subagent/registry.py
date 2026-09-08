"""子智能体注册表 — 按 name 管理 SubAgentDefinition。"""
from __future__ import annotations

import logging
from typing import Optional

from app.subagent.definition import SubAgentDefinition

logger = logging.getLogger(__name__)

_registry: dict[str, SubAgentDefinition] = {}


def register(definition: SubAgentDefinition) -> None:
    _registry[definition.name] = definition
    logger.info(f"[SubAgentRegistry] registered: {definition.name}")


def get(name: str) -> Optional[SubAgentDefinition]:
    return _registry.get(name)


def list_available() -> list[SubAgentDefinition]:
    return list(_registry.values())


def list_names() -> list[str]:
    return list(_registry.keys())
