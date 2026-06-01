from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL_CHAT: str = "deepseek-chat"
    DEEPSEEK_MODEL_REASONER: str = "deepseek-reasoner"
    DEEPSEEK_MAX_TOKENS: int = 4096
    DEEPSEEK_TIMEOUT_SECONDS: float = 60.0
    DEEPSEEK_RETRY_MAX: int = 2

    SUPABASE_URL: str | None = None
    SUPABASE_SERVICE_KEY: str | None = None

    EMBEDDING_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    EMBEDDING_API_KEY: str | None = None
    EMBEDDING_MODEL: str = "embedding-3"
    EMBEDDING_DIMENSIONS: int = 1024
    EMBEDDING_TIMEOUT_SECONDS: float = 20.0

    RAG_TOP_K: int = 8
    RAG_MIN_SIMILARITY: float = 0.30

    CORS_ALLOW_ORIGINS: str = "*"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.SUPABASE_URL and self.SUPABASE_SERVICE_KEY)

    @property
    def rag_enabled(self) -> bool:
        return self.supabase_enabled and bool(self.EMBEDDING_API_KEY)


settings = Settings()
