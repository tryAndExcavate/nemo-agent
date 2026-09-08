"""ConversationHistoryReader — 只读访问某一个 conversation_id 的 JSONL 历史。

构造时就把路径锁死，之后任何方法都不接受 conversation_id 参数，
杜绝"顺手查询别的会话"的可能性。

适配项目实际的 JSONL 格式：每行一条消息（role + content）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class HistoryRecord:
    """从 JSONL 中提取的一条历史记录（一条消息或一组连续消息的摘要）。"""
    id: str
    turn: int
    role: str
    content: str
    full_text: str  # 完整内容


_SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def _resolve_safe_path(sessions_root: Path, conversation_id: str) -> Path:
    """防止 conversation_id 被拼接出目录穿越。"""
    if not _SAFE_ID_PATTERN.fullmatch(conversation_id):
        raise ValueError(f"invalid conversation_id: {conversation_id}")
    root = sessions_root.resolve()
    path = (root / f"{conversation_id}.jsonl").resolve()
    if path.parent != root:
        raise PermissionError("resolved history path escaped sessions_root")
    return path


class ConversationHistoryReader:
    """
    只读访问某一个 conversation_id 的 JSONL 历史。
    构造时路径锁死，之后不接受 conversation_id 参数。
    """

    def __init__(self, sessions_root: Path, conversation_id: str):
        self._path = _resolve_safe_path(sessions_root, conversation_id)
        self._cache: list[HistoryRecord] | None = None

    def _load(self) -> list[HistoryRecord]:
        if self._cache is not None:
            return self._cache

        records: list[HistoryRecord] = []
        if not self._path.exists():
            return records

        turn = 0
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = obj.get("role", "unknown")
                content = self._extract_content(obj)
                if not content:
                    continue

                turn += 1
                records.append(HistoryRecord(
                    id=f"{self._path.stem}-{turn}",
                    turn=turn,
                    role=role,
                    content=content[:200],
                    full_text=content,
                ))

        self._cache = records
        return records

    def _extract_content(self, obj: dict) -> str:
        """从消息 dict 中提取纯文本内容，兼容多种格式。"""
        # 1. 直接是字符串（旧格式）
        c = obj.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            # OpenAI 多模态格式 或 content blocks
            parts = []
            for block in c:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        pass  # 跳过 thinking block
                    elif block.get("type") == "tool_use":
                        parts.append(f"[调用工具: {block.get('name', '?')}]")
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts)
        return ""

    def list_index(self) -> list[dict]:
        """返回目录（仅摘要）。"""
        records = self._load()
        return [
            {"id": r.id, "turn": r.turn, "role": r.role, "content": r.content}
            for r in records
        ]

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """关键词搜索（兼容中英文），已绑定当前会话，不需要 conversation_id。"""
        # 中文按字符拆分 + 英文按空格拆分，合并
        import re as _re
        query_chars = set(_re.findall(r"[一-鿿]", query))
        query_words = set(query.lower().split())
        query_terms = query_chars | query_words
        if not query_terms:
            return []

        scored: list[tuple[int, HistoryRecord]] = []
        for r in self._load():
            pool = (r.content + " " + r.full_text).lower()
            # 中文逐字匹配 + 英文按词匹配
            cjk_hits = sum(1 for c in query_chars if c in pool)
            word_hits = sum(1 for w in query_words if w in pool)
            overlap = cjk_hits + word_hits
            if overlap > 0:
                scored.append((overlap, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": r.id, "turn": r.turn, "role": r.role, "content": r.content}
            for _, r in scored[:top_k]
        ]

    def get_detail(self, record_id: str) -> Optional[HistoryRecord]:
        for r in self._load():
            if r.id == record_id:
                return r
        return None
