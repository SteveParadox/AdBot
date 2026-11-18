from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADBOT_", env_file="../.env", extra="ignore", hide_input_in_errors=True)
    environment: Literal["development", "production"] = "development"
    trusted_proxy_cidrs: str = ""
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    enforce_https: bool = False
    hsts_enabled: bool = False
    user_agent_default: str = "Adbot/1.0.0"
    user_agent_max_length: int = Field(512, ge=32, le=2048)
    user_agent_allow_request_overrides: bool = False
    user_agent_rotatable_services: str = ""
    user_agent_fixed_identities: dict[str, str] = Field(default_factory=dict)
    outbound_proxy_enabled: bool = False
    outbound_proxy_config_path: Path = Path('/run/secrets/outbound-proxies.json')
    outbound_connect_timeout_seconds: float = Field(5, gt=0, le=60)
    outbound_request_timeout_seconds: float = Field(15, gt=0, le=120)
    outbound_max_retries: int = Field(2, ge=0, le=4)
    outbound_health_interval_seconds: int = Field(60, ge=10, le=3600)
    public_rate_per_minute: int = Field(600, ge=1)

    api_keys: str = ""
    content_admin_keys: str = ""
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
    ai_provider: Literal["disabled", "groq", "openai_compatible", "local"] = "disabled"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: SecretStr = SecretStr("")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: SecretStr = SecretStr("")
    ai_model: str = ""
    ai_timeout_seconds: int = Field(30, ge=1, le=120)
    ai_ollama_native: bool = False
    ai_ollama_warmup_timeout_seconds: int = Field(300, ge=1, le=600)
    ai_primary_fallback_timeout_seconds: int = Field(10, ge=1, le=120)
    ai_fallback_provider: Literal["disabled", "local"] = "disabled"
    ai_fallback_base_url: str = "http://127.0.0.1:11434/v1"
    ai_fallback_api_key: SecretStr = SecretStr("")
    ai_fallback_model: str = ""
    ai_fallback_timeout_seconds: int = Field(60, ge=1, le=600)
    agent_fallback_tokens: int = Field(10000, ge=0, le=250000)
    ai_retries: int = Field(2, ge=0, le=4)
    ai_max_output_tokens: int = Field(800, ge=256, le=8000)
    ai_max_request_chars: int = Field(18000, ge=4000, le=100000)
    ai_json_mode: bool = True
    agent_max_steps: int = Field(500, ge=1, le=500)
    agent_max_tokens: int = Field(60000, ge=2000, le=1000000)
    agent_max_tabs: int = Field(4, ge=1, le=10)
    agent_max_retries: int = Field(3, ge=1, le=10)
    agent_memory_enabled: bool = True
    agent_visual_reasoning: bool = False
    browser_session_persistence: bool = False
    session_encryption_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def secure(self):
        from ipaddress import ip_network
        for value in filter(None, (v.strip() for v in self.trusted_proxy_cidrs.split(","))):
            if ip_network(value).prefixlen == 0:
                raise ValueError("Trust explicit proxy networks, never all addresses")
        hosts = [h.strip() for h in self.allowed_hosts.split(",")]
        if not all(hosts) or (self.environment == "production" and "*" in hosts):
            raise ValueError("Configure explicit allowed hosts")
        if self.hsts_enabled and not self.enforce_https:
            raise ValueError("HSTS requires verified HTTPS enforcement")
        if "*" in self.cors_origins.split(","):
            raise ValueError("CORS origins must be explicit")
        ua_values = [self.user_agent_default, *self.user_agent_fixed_identities.values()]
        if any(not v or len(v)>self.user_agent_max_length or v != v.strip() or any(ord(c)<32 or ord(c)>126 for c in v) for v in ua_values):
            raise ValueError("Invalid operator User-Agent identity")
        ua_services = {'browser','ai','ai_local','proxy_health'}
        if set(self.user_agent_fixed_identities)-ua_services or any(v.strip() not in ua_services for v in self.user_agent_rotatable_services.split(',') if v.strip()):
            raise ValueError("Unknown User-Agent service")
        keys = self.api_keys.split(",")
        if not keys or any(len(k.strip()) < 32 for k in keys):
            raise ValueError("Set ADBOT_API_KEYS to comma-separated API keys of at least 32 characters")
        if self.environment == "production":
            if self.fixture_mode or not self.redis_url or not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL, Redis and fixture mode disabled")
            if not any(d.strip() for d in self.authorized_domains.split(",")):
                raise ValueError("Production requires ADBOT_AUTHORIZED_DOMAINS")
        if self.ai_provider != "disabled":
            if not self.ai_model:
                raise ValueError("Set ADBOT_AI_MODEL when enabling an AI provider")
            endpoint = self.groq_base_url if self.ai_provider == "groq" else self.ai_base_url
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
            ):
                raise ValueError("Invalid AI endpoint")
            if self.ai_provider != "local" and parsed.scheme != "https":
                raise ValueError("Remote AI providers require HTTPS")
            key = self.groq_api_key if self.ai_provider == "groq" else self.ai_api_key
            if self.ai_provider != "local" and not key.get_secret_value():
                raise ValueError("Configure the selected provider API key")
        if self.ai_fallback_provider != "disabled":
            if self.ai_provider != "groq":
                raise ValueError("AI fallback is supported only with Groq as the primary provider")
            if not self.ai_fallback_model:
                raise ValueError("Set ADBOT_AI_FALLBACK_MODEL when enabling the local fallback")
            parsed = urlsplit(self.ai_fallback_base_url)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
            ):
                raise ValueError("Invalid local AI fallback endpoint")
            if self.agent_fallback_tokens < self.ai_max_output_tokens:
                raise ValueError("AI fallback token reserve must cover at least one maximum-length response")
        if self.browser_session_persistence:
            from cryptography.fernet import Fernet

            try:
                Fernet(self.session_encryption_key.get_secret_value().encode())
            except Exception as exc:
                raise ValueError("Session persistence requires a valid ADBOT_SESSION_ENCRYPTION_KEY") from exc
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
