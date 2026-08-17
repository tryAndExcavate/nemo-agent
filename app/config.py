from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Server
    server_port: int = 8888

    # DeepSeek LLM (对话模型)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"
    deepseek_chat_temperature: float = 0.7

    # DashScope Embedding (向量模型)
    dashscope_api_key: str = ""
    dashscope_embedding_model: str = "text-embedding-v4"
    dashscope_embedding_dimension: int = 1024

    # MySQL
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "root"
    mysql_database: str = "dodo"

    # Redis
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None

    # MinIO
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_name: str = "rag-test2"
    minio_secure: bool = False

    # PostgreSQL pgvector
    pgvector_host: str = "127.0.0.1"
    pgvector_port: int = 5432
    pgvector_database: str = "vector_store"
    pgvector_user: str = "postgres"
    pgvector_password: str = "postgres"

    # Tavily Search
    tavily_api_key: str = ""
    tavily_mcp_url: str = "https://mcp.tavily.com/mcp/"

    # Skills
    skills_directory: str = ""

    # Image Generation
    grsai_nanobanana_api_key: str = ""

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )

    @property
    def pgvector_url(self) -> str:
        return (
            f"postgresql://{self.pgvector_user}:{self.pgvector_password}"
            f"@{self.pgvector_host}:{self.pgvector_port}/{self.pgvector_database}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
