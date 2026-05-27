from pydantic_settings import BaseSettings
from pydantic import Field


class LLMServiceConfig(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8900

    provider_base_url: str = "https://api.deepseek.com/chat/completions"
    provider_api_key: str = ""
    provider_model: str = "deepseek-chat"
    provider_headers: dict = Field(default_factory=dict)
    provider_timeout: int = 30
    provider_bypass_proxy: bool = False

    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4/embeddings"
    embedding_api_key: str = ""
    embedding_model: str = "embedding-3"
    embedding_dimensions: int = 1024
    rerank_base_url: str = "https://open.bigmodel.cn/api/paas/v4/rerank"
    rerank_api_key: str = ""
    rerank_model: str = ""
    model_timeout: int = 60
    model_bypass_proxy: bool = False
    model_extra_headers: dict = Field(default_factory=dict)

    worker_concurrency: int = 4
    default_max_attempts: int = 3
    retry_backoff_base: float = 2.0
    retry_backoff_max: float = 60.0

    execute_timeout: int = 60
    lease_duration: int = 300

    model_config = {"env_prefix": "LLM_SERVICE_", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
