"""LiveMemoryReadOnlyView — 借给子 Agent 的只读窗口。

子 Agent 拿到的是这个 View，永远拿不到写入接口（add_chunk 等）。
使用 name mangling（双下划线）防止子类或工具意外拿到写接口。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MemoryChunk:
    """一条记忆片段，封装从原始消息中提取的关键信息。"""
    id: str
    turn: int
    summary: str          # 摘要（取前 200 字符）
    full_text: str        # 完整文本内容
    role: str             # user / assistant / system
    timestamp: float = 0.0


class LiveMemoryStore:
    """主 Agent 运行期的实时记忆存储（仅主 Agent 持有写权限）。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._chunks: list[MemoryChunk] = []
        self._counter: int = 0

    def add_message(self, role: str, content: str, timestamp: float = 0.0) -> None:
        """主 Agent 调用：把消息写入 live memory。"""
        text = content if isinstance(content, str) else str(content)
        if not text.strip():
            return
        self._counter += 1
        self._chunks.append(MemoryChunk(
            id=f"live-{self.session_id}-{self._counter}",
            turn=self._counter,
            summary=text[:200],
            full_text=text,
            role=role,
            timestamp=timestamp,
        ))

    def list_index(self) -> list[dict]:
        """返回目录（仅摘要）。"""
        return [
            {"id": c.id, "turn": c.turn, "summary": c.summary, "role": c.role}
            for c in self._chunks
        ]

    def search_keyword(self, query: str, top_k: int = 5) -> list[dict]:
        """关键词搜索（兼容中英文）。"""
        import re as _re
        query_chars = set(_re.findall(r"[??]", query))
        query_words = set(query.lower().split())
        query_terms = query_chars | query_words
        if not query_terms:
            return []

        scored: list[tuple[int, MemoryChunk]] = []
        for c in self._chunks:
            pool = (c.summary + " " + c.full_text).lower()
            cjk_hits = sum(1 for ch in query_chars if ch in pool)
            word_hits = sum(1 for w in query_words if w in pool)
            overlap = cjk_hits + word_hits
            if overlap > 0:
                scored.append((overlap, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": c.id, "turn": c.turn, "summary": c.summary, "role": c.role}
            for _, c in scored[:top_k]
        ]

    def get_detail(self, chunk_id: str) -> Optional[MemoryChunk]:
        for c in self._chunks:
            if c.id == chunk_id:
                return c
        return None


class LiveMemoryReadOnlyView:
    """子 Agent 拿到的只读视图，暴露读方法，永远拿不到写接口。"""

    def __init__(self, store: LiveMemoryStore):
        self.__store = store  # name mangling：子类/工具拿不到

    def list_index(self) -> list[dict]:
        return self.__store.list_index()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        return self.__store.search_keyword(query, top_k)

    def get_detail(self, chunk_id: str) -> Optional[MemoryChunk]:
        return self.__store.get_detail(chunk_id)
