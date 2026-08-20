"""JSONL 格式的 usage 日志记录器。"""
import json
import os
from datetime import datetime
from pathlib import Path


class UsageLogger:
    """将每次 LLM 调用的 token 消耗追加写入 JSONL 文件，按日期分割。"""

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        usage: dict,
        model_id: str = "",
        model_name: str = "",
        provider: str = "",
        conversation_id: str = "",
        agent_type: str = "",
    ):
        """记录一条 usage 日志到 JSONL 文件。"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "conversation_id": conversation_id,
            "agent_type": agent_type,
            **usage,
        }

        today = datetime.utcnow().strftime("%Y-%m-%d")
        filepath = self.log_dir / f"usage_{today}.jsonl"

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# 全局单例
usage_logger = UsageLogger()
