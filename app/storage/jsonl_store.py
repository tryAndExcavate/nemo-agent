"""会话存储：JSONL 作为 source of truth。

每个对话一个文件，每行一条消息，追加写入，崩溃安全。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from app.models.query_engine import (
    Message,
    message_to_dict,
    dict_to_message,
)


class JSONLSessionStore:
    def __init__(self, base_dir: str = ".sessions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, conversation_id: str) -> Path:
        return self.base_dir / f"{conversation_id}.jsonl"

    def append_message(self, conversation_id: str, msg: Message) -> None:
        """
        追加单条消息。这是最高频的操作——每次 QueryEngine 产生一条新消息
        （用户输入、assistant 回复、工具结果）都应该立即调用这个方法，
        而不是攒到最后统一写，这样即使程序中途崩溃，已发生的对话也不会丢。
        """
        path = self._path_for(conversation_id)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message_to_dict(msg), ensure_ascii=False) + "\n")

    def load_all(self, conversation_id: str) -> list[Message]:
        """加载一个会话的完整历史"""
        path = self._path_for(conversation_id)
        if not path.exists():
            return []

        messages: list[Message] = []
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(dict_to_message(json.loads(line)))
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    # 单行损坏不应该导致整个会话读取失败
                    print(f"[警告] {conversation_id} 第 {line_no} 行损坏，已跳过: {e}")
                    continue
        return messages

    def iter_messages(self, conversation_id: str) -> Iterator[Message]:
        """流式读取，避免大会话一次性加载进内存"""
        path = self._path_for(conversation_id)
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield dict_to_message(json.loads(line))

    def list_conversation_ids(self) -> list[str]:
        return [p.stem for p in self.base_dir.glob("*.jsonl")]

    def delete(self, conversation_id: str) -> None:
        path = self._path_for(conversation_id)
        if path.exists():
            path.unlink()
        # 同时删除元数据
        meta_path = self.base_dir / f"{conversation_id}.meta.json"
        if meta_path.exists():
            meta_path.unlink()

    def save_meta(self, conversation_id: str, meta: dict) -> None:
        """保存任务元数据（workspace_path、tokens 等）"""
        meta_path = self.base_dir / f"{conversation_id}.meta.json"
        # 合并已有元数据
        existing = {}
        if meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.update(meta)
        meta_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_meta(self, conversation_id: str) -> dict:
        """读取任务元数据"""
        meta_path = self.base_dir / f"{conversation_id}.meta.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_compressed_summary(self, conversation_id: str, data: dict) -> None:
        """保存上下文压缩摘要（独立于 JSONL 完整历史）"""
        path = self.base_dir / f"{conversation_id}.summary.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_compressed_summary(self, conversation_id: str) -> dict | None:
        """读取上下文压缩摘要，不存在返回 None"""
        path = self.base_dir / f"{conversation_id}.summary.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def rewrite_all(self, conversation_id: str, messages: list[Message]) -> None:
        """
        整体重写，仅用于"编辑历史/压缩上下文"这类需要替换整个会话的场景。
        平时的正常对话流程应该用 append_message，不要用这个。
        """
        path = self._path_for(conversation_id)
        tmp_path = path.with_suffix(".jsonl.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(message_to_dict(msg), ensure_ascii=False) + "\n")
        tmp_path.replace(path)  # 原子替换，避免重写过程中崩溃导致文件损坏
