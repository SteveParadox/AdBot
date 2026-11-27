from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    max_io_threads: int = Field(4, ge=1, le=32)
    max_proxy_connections: int = Field(64, ge=1, le=1024)
    extraction_max_export_bytes: int = Field(52428800, ge=1024, le=209715200)
    extraction_export_ttl_seconds: int = Field(86400, ge=60, le=604800)
    max_concurrent_agents: int = Field(2, ge=1, le=8)
    max_browser_sessions: int = Field(2, ge=1, le=8)
    priority_aging_seconds: int = Field(300, ge=1, le=86400)
    resource_monitoring_enabled: bool = True
    max_host_memory_percent: float = Field(95, gt=0, le=100)
    max_host_cpu_percent: float = Field(95, gt=0, le=100)
    lease_seconds: int = Field(90, ge=30)
    artifact_dir: Path = Path("./data/screenshots")
    retention_days: int = Field(30, ge=1)
    rate_per_minute: int = Field(120, ge=1)
    ai_provider: Literal["disabled", "groq", "groq_secondary", "openrouter", "google", "nvidia", "openai_compatible", "local"] = "disabled"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: SecretStr = SecretStr("")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-120b"
    groq_secondary_api_key: SecretStr = SecretStr("")
    groq_secondary_model: str = "openai/gpt-oss-120b"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "openai/gpt-oss-120b"
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    google_api_key: SecretStr = SecretStr("")
    google_model: str = "gemini-3.8-flash"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_api_key: SecretStr = SecretStr("")
    nvidia_thinking_enabled: bool = False
    nvidia_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    # Empty retains the single-provider / optional local fallback configuration.
    ai_provider_order: str = ""
    ai_failure_cooldown_seconds: int = Field(30, ge=1, le=3600)
    ai_model: str = ""
    ai_timeout_seconds: int = Field(60, ge=1, le=120)
    ai_ollama_native: bool = False
    ai_ollama_context_tokens: int = Field(8192, ge=2048, le=32768)
    ai_ollama_warmup_timeout_seconds: int = Field(300, ge=1, le=600)
    ai_primary_fallback_timeout_seconds: int = Field(30, ge=1, le=120)
    ai_fallback_provider: Literal["disabled", "local"] = "disabled"
    ai_fallback_base_url: str = "http://127.0.0.1:11434/v1"
    ai_fallback_api_key: SecretStr = SecretStr("")
    ai_fallback_model: str = ""
    ai_fallback_timeout_seconds: int = Field(60, ge=1, le=600)
    agent_fallback_tokens: int = Field(10000, ge=0, le=250000)
    ai_provider_rpm: int = Field(0, ge=0, le=1000000)
    ai_provider_tpm: int = Field(0, ge=0, le=1000000000)
    ai_retries: int = Field(2, ge=0, le=4)
    ai_max_output_tokens: int = Field(4096, ge=256, le=8000)
    ai_max_request_chars: int = Field(36000, ge=4000, le=100000)
    ai_json_mode: bool = True
    ai_context_windows: dict[str, int] = Field(default_factory=dict)
    ai_reasoning_effort: Literal["auto", "low", "medium", "high"] = "auto"
    agent_max_evidence_records: int = Field(80, ge=1, le=200)
    agent_collection_max_rows: int = Field(5000, ge=1, le=10000)
    agent_collection_batch_rows: int = Field(250, ge=1, le=1000)
    agent_collection_max_bytes: int = Field(8_000_000, ge=4096, le=16_000_000)
    agent_classification_batch_rows: int = Field(24, ge=1, le=40)
    agent_classification_max_calls: int = Field(32, ge=0, le=40)
    agent_classification_concurrency: int = Field(2, ge=1, le=4)
    agent_max_steps: int = Field(500, ge=1, le=500)
    agent_max_tokens: int = Field(250000, ge=2000, le=1000000)
    agent_max_tabs: int = Field(6, ge=1, le=10)
    agent_default_target_max_pages: int = Field(100, ge=1, le=1000)
    agent_default_target_max_duration_seconds: int = Field(3600, ge=5, le=3600)
    agent_max_retries: int = Field(3, ge=1, le=10)
    agent_memory_enabled: bool = True
    agent_visual_reasoning: bool = True
    # Exact provider:model entries for additional vision-capable deployments.
    ai_vision_models: str = ""
    browser_session_persistence: bool | None = None
    session_encryption_key: SecretStr = SecretStr("")

    @field_validator("ai_provider_order", mode="before")
    @classmethod
    def normalize_provider_order(cls, value):
        return value.strip() if isinstance(value, str) else value

    def provider_endpoint(self, name):
        if name == "groq":
            return self.groq_base_url, self.groq_api_key, self.ai_model if name == self.ai_provider else self.groq_model
        if name == "groq_secondary":
            return (self.groq_base_url, self.groq_secondary_api_key,
                    self.ai_model if name == self.ai_provider else self.groq_secondary_model)
        if name in {"openrouter", "google", "nvidia"}:
            return (getattr(self, name + "_base_url"), getattr(self, name + "_api_key"),
                    self.ai_model if name == self.ai_provider else getattr(self, name + "_model"))
        if name in {"openai_compatible", "local"}:
            return self.ai_base_url, self.ai_api_key, self.ai_model
        raise ValueError("Unknown AI provider in ADBOT_AI_PROVIDER_ORDER")

    def model_providers(self):
        if self.ai_provider == "disabled":
            return []
        if self.ai_provider_order:
            return [self.provider_endpoint(name.strip()) for name in self.ai_provider_order.split(",")]
        providers = [self.provider_endpoint(self.ai_provider)]
        if self.ai_fallback_provider == "local":
            providers.append((self.ai_fallback_base_url, self.ai_fallback_api_key, self.ai_fallback_model))
        return providers

    def model_provider_is_local(self, index):
        if self.ai_provider_order:
            return self.ai_provider_order.split(",")[index].strip() == "local"
        return self.ai_provider == "local" or (index > 0 and self.ai_fallback_provider == "local")

    def supports_vision(self, provider: str, model: str, *, native: bool = False) -> bool:
        if not self.agent_visual_reasoning or native or provider == "disabled":
            return False
        configured = {item.strip() for item in self.ai_vision_models.split(",") if item.strip()}
        return (f"{provider}:{model}" in configured
                or (provider == "google" and model.startswith("gemini-")))

    def vision_available(self) -> bool:
        names = ([name.strip() for name in self.ai_provider_order.split(",")]
                 if self.ai_provider_order else [self.ai_provider, "local"])
        return any(self.supports_vision(names[index], model,
                                        native=self.model_provider_is_local(index) and self.ai_ollama_native)
                   for index, (_, _, model) in enumerate(self.model_providers()))

    def ollama_context_for(self, model: str) -> int:
        return min(
            self.ai_ollama_context_tokens,
            self.ai_context_windows.get("local", self.ai_ollama_context_tokens),
            self.ai_context_windows.get(model, self.ai_ollama_context_tokens),
        )

    def reasoning_effort_for(self, purpose: str) -> str:
        if self.ai_reasoning_effort != "auto":
            return self.ai_reasoning_effort
        if purpose in {"plan", "verify"}:
            return "high"
        return "medium" if purpose == "decide" else "low"

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
        if any(value < 256 for value in self.ai_context_windows.values()):
            raise ValueError("Model context windows must be at least 256 tokens")
        if self.ai_provider != "disabled":
            if not self.ai_model:
                raise ValueError("Set ADBOT_AI_MODEL when enabling an AI provider")
            endpoint, key, _ = self.provider_endpoint(self.ai_provider)
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
            if self.ai_provider != "local" and not key.get_secret_value():
                raise ValueError("Configure the selected provider API key")
        if self.ai_provider_order and self.ai_provider != "disabled":
            names = [name.strip() for name in self.ai_provider_order.split(",")]
            if names[0] != self.ai_provider or len(names) != len(set(names)):
                raise ValueError("AI provider order must start with AI_PROVIDER and contain no duplicates")
            if self.ai_fallback_provider != "disabled":
                raise ValueError("Use AI_PROVIDER_ORDER or the legacy local fallback, not both")
            for index, (endpoint, key, model) in enumerate(self.model_providers()):
                parsed = urlsplit(endpoint)
                if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                        or parsed.password or parsed.query or parsed.fragment):
                    raise ValueError("Invalid AI provider chain endpoint")
                if not model:
                    raise ValueError("Configure a model for each AI provider")
                if not self.model_provider_is_local(index) and (parsed.scheme != "https" or not key.get_secret_value()):
                    raise ValueError("Remote AI provider chain entries require HTTPS and an API key")
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
        # Auto-enable only when a durable operator-provided key is available.
        if self.browser_session_persistence is None:
            self.browser_session_persistence = bool(self.session_encryption_key.get_secret_value())
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
