from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADBOT_", env_file="../.env", extra="ignore")
    environment: str = "development"
    api_keys: str = ""
    database_url: str = "sqlite:///./adbot.db"
    redis_url: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    authorized_domains: str = ""
    fixture_mode: bool = False
    fixture_port: int = 8765
    max_concurrency: int = Field(2, ge=1, le=8)
    lease_seconds: int = Field(90, ge=30)
    artifact_dir: Path = Path("./data/screenshots")
    retention_days: int = Field(30, ge=1)
    rate_per_minute: int = Field(120, ge=1)

    @model_validator(mode="after")
    def secure(self):
        keys = self.api_keys.split(",")
        if not keys or any(len(k.strip()) < 32 for k in keys):
            raise ValueError("Set ADBOT_API_KEYS to comma-separated API keys of at least 32 characters")
        if self.environment == "production":
            if self.fixture_mode or not self.redis_url or not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL, Redis and fixture mode disabled")
            if not self.authorized_domains:
                raise ValueError("Production requires ADBOT_AUTHORIZED_DOMAINS")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
