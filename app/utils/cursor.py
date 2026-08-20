"""游标编码/解码工具，用于会话列表的高效分页。"""
import base64
import json
from datetime import datetime
from typing import Optional, Tuple


def encode_cursor(last_message_at: datetime, conversation_id: int) -> str:
    """把 (时间, id) 组合编码成一个不透明字符串给前端，前端不需要理解内部结构。"""
    payload = {"t": last_message_at.isoformat(), "id": conversation_id}
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> Optional[Tuple[datetime, int]]:
    """解码游标字符串，返回 (时间, id)。"""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["t"]), payload["id"]
    except Exception:
        return None
