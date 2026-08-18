"""llm_core.blueprint_db - 蓝图版本化存储表。

每次保存生成一条新版本记录（而非覆盖），支持草稿(draft)/发布(published)分离
与版本历史回滚。与 llm_core.store 共用同一个 SQLite 库(engine) 与 SQLModel.metadata。
"""
from datetime import datetime
import uuid

from sqlmodel import SQLModel, Field

from llm_core.store import engine


class BlueprintVersion(SQLModel, table=True):
    """每次保存生成一条新记录，实现版本历史。"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    agent_id: str = Field(index=True)
    version: int                      # 该 agent 下自增版本号
    graph_json: str                   # LiteGraph.serialize() 的完整 JSON
    status: str = "draft"             # draft / published
    message: str = ""                 # 类似 git commit message，方便回滚时识别
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "default_user"


class BlueprintPointer(SQLModel, table=True):
    """记录每个 agent 当前"正在运行"的已发布版本，运行时只认这张表。"""
    agent_id: str = Field(primary_key=True)
    published_version_id: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# 与 store 共用同一个 SQLModel.metadata，把新表一并建到 models.db
SQLModel.metadata.create_all(engine)
