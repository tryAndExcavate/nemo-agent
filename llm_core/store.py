"""llm_core.store - 模型配置存储（SQLite） + api_key Fernet 加密。

说明：
- 数据文件 models.db 放在项目根目录。
- 加密密钥从 app.config.settings.model_config_secret_key 读取；
  若未配置，则自动生成一个 Fernet 密钥并落盘到项目根 models_secret.key，
  保证默认配置也能启动，绝不因密钥缺失而崩溃。
"""
import json
import logging
import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet
from sqlmodel import SQLModel, Field, Session, create_engine, select

logger = logging.getLogger(__name__)

# 项目根目录（llm_core 包所在目录的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "models.db"
SECRET_KEY_PATH = PROJECT_ROOT / "models_secret.key"


def _load_or_generate_fernet() -> Fernet:
    """从配置读取密钥，缺失则自动生成并落盘。"""
    try:
        from app.config import settings
        configured = (settings.model_config_secret_key or "").strip()
    except Exception as e:  # 兜底：app 配置不可用时也不崩溃
        logger.warning(f"读取 app.config.settings 失败，将自动生成密钥: {e}")
        configured = ""

    key = configured.encode() if configured else b""

    # 校验配置的密钥是否为合法 Fernet key；不合法则兜底到本地自动生成
    try:
        if key:
            Fernet(key)  # 触发校验
            return Fernet(key)
    except Exception as e:
        logger.warning(f"配置的 MODEL_CONFIG_SECRET_KEY 不是合法的 Fernet key，改用自动生成: {e}")

    # 自动生成并落盘，保证密钥跨进程可复用
    if SECRET_KEY_PATH.exists():
        stored = SECRET_KEY_PATH.read_text(encoding="utf-8").strip().encode()
        try:
            return Fernet(stored)
        except Exception as e:
            logger.warning(f"models_secret.key 内容无效，重新生成: {e}")

    new_key = Fernet.generate_key()
    SECRET_KEY_PATH.write_text(new_key.decode(), encoding="utf-8")
    logger.info(f"已自动生成模型配置加密密钥: {SECRET_KEY_PATH}")
    return Fernet(new_key)


fernet = _load_or_generate_fernet()

# 线程锁：sqlmodel/SQLAlchemy 的 sync Session 并发写 SQLite 时保护
_lock = threading.Lock()


class ModelConfigDB(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str  # 展示名，用户自定义，如 "DeepSeek-V3-主力"
    provider_type: str  # 对应 AdapterRegistry 的 key
    base_url: str
    model_name: str  # 平台侧真实 model 名，如 "deepseek-chat"
    api_key_encrypted: str
    extra_config: str = "{}"  # JSON 字符串，存放温度/自定义 header 等
    enabled: bool = True


class ActiveModelDB(SQLModel, table=True):
    """基座当前激活（挂载）的模型，单行状态表。

    key 固定为 "active"。用独立表而非给 ModelConfigDB 加列，
    保证同时只有一个激活模型、可随时拔出（清空）而不污染模型本身。
    """

    key: str = Field(primary_key=True)
    model_id: str | None = None


class ActiveSummaryModelDB(SQLModel, table=True):
    """摘要模型挂载槽位，用于上下文管理和摘要生成。

    key 固定为 "active_summary"。独立于基座模型，可单独配置。
    """

    key: str = Field(primary_key=True)
    model_id: str | None = None


class ActiveSubAgentModelDB(SQLModel, table=True):
    """子 Agent 模型挂载槽位，用于子代理任务执行。

    key 固定为 "active_sub_agent"。独立于基座和摘要模型，可单独配置。
    """

    key: str = Field(primary_key=True)
    model_id: str | None = None


engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def _to_db_item(item: ModelConfigDB) -> dict:
    """把数据库行转成不包含明文 api_key 的公开表示。"""
    return {
        "id": item.id,
        "name": item.name,
        "provider_type": item.provider_type,
        "base_url": item.base_url,
        "model_name": item.model_name,
        "enabled": item.enabled,
    }


class ConfigStore:
    """模型配置的持久化存储：save / get_decrypted / list_all / delete。"""

    @staticmethod
    def save(model_id: str, name, provider_type, base_url, model_name,
             api_key: str, extra_config: dict, enabled: bool = True):
        with _lock:
            with Session(engine) as s:
                enc = fernet.encrypt(api_key.encode()).decode()
                item = ModelConfigDB(
                    id=model_id, name=name, provider_type=provider_type,
                    base_url=base_url, model_name=model_name,
                    api_key_encrypted=enc,
                    extra_config=json.dumps(extra_config, ensure_ascii=False),
                    enabled=enabled,
                )
                s.merge(item)
                s.commit()
        logger.info(f"保存模型配置: id={model_id} name={name} provider={provider_type}")

    @staticmethod
    def get_decrypted(model_id: str) -> dict:
        with _lock:
            with Session(engine) as s:
                item = s.get(ModelConfigDB, model_id)
                if not item:
                    raise ValueError(f"模型不存在: {model_id}")
                config = {
                    "id": item.id,
                    "name": item.name,
                    "provider_type": item.provider_type,
                    "base_url": item.base_url,
                    "model_name": item.model_name,
                    "api_key": fernet.decrypt(item.api_key_encrypted.encode()).decode(),
                    "enabled": item.enabled,
                }
                try:
                    config.update(json.loads(item.extra_config or "{}"))
                except json.JSONDecodeError:
                    logger.warning(f"模型 {model_id} 的 extra_config 解析失败，忽略")
        return config

    @staticmethod
    def list_all() -> list[dict]:
        with _lock:
            with Session(engine) as s:
                items = s.exec(select(ModelConfigDB)).all()
                return [_to_db_item(i) for i in items]

    @staticmethod
    def get_basic(model_id: str) -> dict:
        """获取单个模型配置的公开（脱敏）信息，供前端编辑回填。"""
        with _lock:
            with Session(engine) as s:
                item = s.get(ModelConfigDB, model_id)
                if not item:
                    raise ValueError(f"模型不存在: {model_id}")
                return _to_db_item(item)

    @staticmethod
    def delete(model_id: str) -> bool:
        """删除一条模型配置，返回是否真的删除了。"""
        with _lock:
            with Session(engine) as s:
                item = s.get(ModelConfigDB, model_id)
                if not item:
                    return False
                s.delete(item)
                s.commit()
        logger.info(f"删除模型配置: id={model_id}")
        return True

    # ===== 基座激活模型（单行状态） =====

    @staticmethod
    def get_active_model_id() -> str | None:
        with _lock:
            with Session(engine) as s:
                row = s.get(ActiveModelDB, "active")
                return row.model_id if row else None

    @staticmethod
    def set_active_model_id(model_id: str):
        with _lock:
            with Session(engine) as s:
                s.merge(ActiveModelDB(key="active", model_id=model_id))
                s.commit()
        logger.info(f"设置基座激活模型: {model_id}")

    @staticmethod
    def clear_active_model():
        with _lock:
            with Session(engine) as s:
                row = s.get(ActiveModelDB, "active")
                if row:
                    s.delete(row)
                    s.commit()
        logger.info("拔出基座激活模型")

    # ===== 摘要模型（上下文管理用） =====

    @staticmethod
    def get_active_summary_model_id() -> str | None:
        with _lock:
            with Session(engine) as s:
                row = s.get(ActiveSummaryModelDB, "active_summary")
                return row.model_id if row else None

    @staticmethod
    def set_active_summary_model_id(model_id: str):
        with _lock:
            with Session(engine) as s:
                s.merge(ActiveSummaryModelDB(key="active_summary", model_id=model_id))
                s.commit()
        logger.info(f"设置摘要模型: {model_id}")

    @staticmethod
    def clear_active_summary_model():
        with _lock:
            with Session(engine) as s:
                row = s.get(ActiveSummaryModelDB, "active_summary")
                if row:
                    s.delete(row)
                    s.commit()
        logger.info("拔出摘要模型")

    @staticmethod
    def get_active_sub_agent_model_id() -> str | None:
        with _lock:
            with Session(engine) as s:
                row = s.get(ActiveSubAgentModelDB, "active_sub_agent")
                return row.model_id if row else None

    @staticmethod
    def set_active_sub_agent_model_id(model_id: str):
        with _lock:
            with Session(engine) as s:
                s.merge(ActiveSubAgentModelDB(key="active_sub_agent", model_id=model_id))
                s.commit()
        logger.info(f"设置子 Agent 模型: {model_id}")

    @staticmethod
    def clear_active_sub_agent_model():
        with _lock:
            with Session(engine) as s:
                row = s.get(ActiveSubAgentModelDB, "active_sub_agent")
                if row:
                    s.delete(row)
                    s.commit()
        logger.info("拔出子 Agent 模型")
