"""Typed configuration for the MCP services.

Precedence (highest first) for every settings group:

1. Environment variables / the local `.env` file.
2. The project YAML config (`config/app.yaml`).
3. Field defaults.

Secrets are only ever read from the environment (or a secret manager that
injects environment variables). They are never read from YAML.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal
from urllib.parse import urlparse

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml"
MCP_SERVICES_CONFIG_PATH = PROJECT_ROOT / "config" / "mcp_services.yaml"


class _YamlSource(PydanticBaseSettingsSource):
    """Settings source backed by a section of the project YAML file."""

    def __init__(self, settings_cls: type[BaseSettings], data: dict[str, Any]) -> None:
        super().__init__(settings_cls)
        self._data = data

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:  # noqa: ARG002
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


def load_yaml_config(path: Path | None = None) -> dict[str, Any]:
    """Load `config/app.yaml`; a missing file yields an empty mapping."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        return {}
    data = yaml.safe_load(config_path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{config_path} must contain a YAML mapping")
    return data


def _resolve_placeholders(value: Any) -> Any:
    """Resolve `${VAR}` placeholders against the environment.

    Unset variables become None and are stripped, so field defaults apply
    instead of a literal `${VAR}` string leaking into runtime configuration.
    """
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1])
    if isinstance(value, dict):
        return {k: _resolve_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_placeholders(item) for item in value]
    return value


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value


def _service_config() -> dict[str, Any]:
    """Load MCP service configuration.

    `config/mcp_services.yaml` holds the MCP-server defaults and takes
    precedence over same-named sections in `config/app.yaml`. Tests and
    deployments can point at another file with `URUMI_MCP_CONFIG`.
    """
    override = os.environ.get("URUMI_MCP_CONFIG")
    if override:
        return load_yaml_config(Path(override))
    merged = dict(load_yaml_config())
    merged.update(load_yaml_config(MCP_SERVICES_CONFIG_PATH))
    return merged


def _yaml_section(name: str) -> dict[str, Any]:
    section = _service_config().get(name)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"config section '{name}' must be a mapping")
    return _strip_none(_resolve_placeholders(section))


class _SectionSettings(BaseSettings):
    """Base class: env/.env override YAML section, which overrides defaults."""

    _yaml_section_name: ClassVar[str] = ""

    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSource(settings_cls, _yaml_section(cls._yaml_section_name)),
            file_secret_settings,
        )


class LoggingSettings(_SectionSettings):
    _yaml_section_name: ClassVar[str] = "logging"

    level: str = Field("INFO", validation_alias="LOG_LEVEL")

    @field_validator("level")
    @classmethod
    def _normalize_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"log level must be one of {sorted(allowed)}")
        return level


class WooCommerceSettings(_SectionSettings):
    """Upstream WooCommerce connection settings.

    `auth_mode`:
      * `auto`   - Basic over HTTPS, OAuth 1.0a otherwise (WooCommerce 11+
                   only accepts Basic auth over HTTPS).
      * `basic`  - HTTP Basic auth.
      * `oauth1` - OAuth 1.0a HMAC-SHA1.
    """

    _yaml_section_name: ClassVar[str] = "woocommerce"

    base_url: str = Field("http://localhost:8080", validation_alias="WOOCOMMERCE_BASE_URL")
    consumer_key: str = Field("", validation_alias="WOOCOMMERCE_CONSUMER_KEY")
    consumer_secret: str = Field("", validation_alias="WOOCOMMERCE_CONSUMER_SECRET")
    auth_mode: Literal["auto", "basic", "oauth1"] = Field(
        "auto", validation_alias="WOOCOMMERCE_AUTH_MODE"
    )
    # WooCommerce verifies OAuth 1.0a signatures against the WordPress site's
    # configured home URL, not the Host used by the client. Set this when they
    # differ (e.g. a container reaching the store via host.docker.internal).
    signing_base_url: str | None = Field(
        None, validation_alias="WOOCOMMERCE_SIGNING_BASE_URL"
    )
    timeout_seconds: float = Field(
        10.0, gt=0, le=120, validation_alias="WOOCOMMERCE_TIMEOUT_SECONDS"
    )
    default_page_size: int = Field(
        20, ge=1, le=100, validation_alias="WOOCOMMERCE_DEFAULT_PAGE_SIZE"
    )
    max_page_size: int = Field(
        100, ge=1, le=100, validation_alias="WOOCOMMERCE_MAX_PAGE_SIZE"
    )
    max_retries: int = Field(2, ge=0, le=5, validation_alias="WOOCOMMERCE_MAX_RETRIES")
    retry_backoff_seconds: float = Field(
        0.5, ge=0, le=10, validation_alias="WOOCOMMERCE_RETRY_BACKOFF_SECONDS"
    )

    @field_validator("signing_base_url")
    @classmethod
    def _validate_signing_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("WOOCOMMERCE_SIGNING_BASE_URL must be an absolute http(s) URL")
        return value

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("WOOCOMMERCE_BASE_URL must be an absolute http(s) URL")
        return value

    @model_validator(mode="after")
    def _validate_pagination(self) -> "WooCommerceSettings":
        if self.default_page_size > self.max_page_size:
            raise ValueError("default_page_size must not exceed max_page_size")
        return self

    @property
    def resolved_auth_mode(self) -> Literal["basic", "oauth1"]:
        if self.auth_mode == "auto":
            return "basic" if self.base_url.startswith("https://") else "oauth1"
        return self.auth_mode

    def require_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("WOOCOMMERCE_CONSUMER_KEY", self.consumer_key),
                ("WOOCOMMERCE_CONSUMER_SECRET", self.consumer_secret),
            )
            if not value
        ]
        if missing:
            from services.common.errors import ConfigurationError

            raise ConfigurationError(
                "missing WooCommerce credentials: " + ", ".join(missing)
            )


class InventorySettings(_SectionSettings):
    """Inventory-specific defaults (thresholds and scan limits)."""

    _yaml_section_name: ClassVar[str] = "inventory"

    low_stock_threshold: int = Field(
        5, ge=0, le=1_000_000, validation_alias="INVENTORY_LOW_STOCK_THRESHOLD"
    )
    summary_max_products: int = Field(
        1000, ge=1, le=100_000, validation_alias="INVENTORY_SUMMARY_MAX_PRODUCTS"
    )
    summary_scan_page_size: int = Field(
        100, ge=1, le=100, validation_alias="INVENTORY_SUMMARY_SCAN_PAGE_SIZE"
    )

    @model_validator(mode="after")
    def _validate_scan(self) -> "InventorySettings":
        if self.summary_scan_page_size > self.max_scan_page_size:
            raise ValueError("summary_scan_page_size exceeds max_scan_page_size")
        return self

    @property
    def max_scan_page_size(self) -> int:
        return 100


class ShippingSettings(_SectionSettings):
    """Shipping mock provider and persistence settings."""

    _yaml_section_name: ClassVar[str] = "shipping_mock"

    mode: Literal["simulated", "degraded", "failing"] = Field(
        "simulated", validation_alias="SHIPPING_MOCK_MODE"
    )
    failure_rate: float = Field(
        0.0, ge=0.0, le=1.0, validation_alias="SHIPPING_MOCK_FAILURE_RATE"
    )
    default_carrier: str = Field(
        "mock-carrier", min_length=1, max_length=64, validation_alias="SHIPPING_DEFAULT_CARRIER"
    )
    tracking_prefix: str = Field(
        "MOCK", min_length=1, max_length=12, validation_alias="SHIPPING_TRACKING_PREFIX"
    )
    delivery_days_min: int = Field(
        3, ge=0, le=365, validation_alias="SHIPPING_DELIVERY_DAYS_MIN"
    )
    delivery_days_max: int = Field(
        5, ge=0, le=365, validation_alias="SHIPPING_DELIVERY_DAYS_MAX"
    )
    database_url: str = Field(
        "sqlite+aiosqlite:///./data/shipping.db", validation_alias="SHIPPING_DATABASE_URL"
    )
    allow_multiple_shipments_per_order: bool = Field(
        False, validation_alias="SHIPPING_ALLOW_MULTIPLE_PER_ORDER"
    )
    timeout_seconds: float = Field(
        10.0, gt=0, le=120, validation_alias="SHIPPING_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(1, ge=0, le=5, validation_alias="SHIPPING_MAX_RETRIES")

    @field_validator("tracking_prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        value = value.strip().upper().replace(" ", "")
        if not value.isalnum():
            raise ValueError("tracking prefix must be alphanumeric")
        return value

    @model_validator(mode="after")
    def _validate_delivery_window(self) -> "ShippingSettings":
        if self.delivery_days_min > self.delivery_days_max:
            raise ValueError("delivery_days_min must not exceed delivery_days_max")
        return self


class GatewaySettings(_SectionSettings):
    """Gateway HTTP, discovery, auth and SSRF settings."""

    _yaml_section_name: ClassVar[str] = "gateway"

    host: str = Field("0.0.0.0", validation_alias="GATEWAY_HOST")
    port: int = Field(8000, ge=1, le=65535, validation_alias="GATEWAY_PORT")
    audit_enabled: bool = Field(True, validation_alias="GATEWAY_AUDIT_ENABLED")
    session_ttl_minutes: int = Field(
        720, ge=5, le=60 * 24 * 30, validation_alias="GATEWAY_SESSION_TTL_MINUTES"
    )
    cookie_secure: bool = Field(False, validation_alias="GATEWAY_COOKIE_SECURE")
    cors_origins: str = Field(
        "http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="GATEWAY_CORS_ORIGINS",
    )
    allowed_hosts: str = Field("", validation_alias="GATEWAY_ALLOWED_HOSTS")
    allowed_origins: str = Field("", validation_alias="GATEWAY_ALLOWED_ORIGINS")
    enable_dns_rebinding_protection: bool = Field(
        True, validation_alias="GATEWAY_ENABLE_DNS_REBINDING_PROTECTION"
    )
    upstream_timeout_seconds: float = Field(
        15.0, gt=0, le=120, validation_alias="GATEWAY_UPSTREAM_TIMEOUT_SECONDS"
    )
    discovery_timeout_seconds: float = Field(
        10.0, gt=0, le=120, validation_alias="GATEWAY_DISCOVERY_TIMEOUT_SECONDS"
    )
    upstream_retries: int = Field(1, ge=0, le=3, validation_alias="GATEWAY_UPSTREAM_RETRIES")
    refresh_interval_seconds: int = Field(
        60, ge=0, le=3600, validation_alias="GATEWAY_REFRESH_INTERVAL_SECONDS"
    )
    allowed_upstream_hosts: str = Field(
        "127.0.0.1,localhost,::1,host.docker.internal,"
        "woocommerce-mcp,inventory-mcp,shipping-mcp,gateway",
        validation_alias="GATEWAY_ALLOWED_UPSTREAM_HOSTS",
    )
    allow_public_upstreams: bool = Field(
        False, validation_alias="GATEWAY_ALLOW_PUBLIC_UPSTREAMS"
    )
    max_page_size: int = Field(100, ge=1, le=500, validation_alias="GATEWAY_MAX_PAGE_SIZE")
    bootstrap_admin_email: str = Field(
        "", validation_alias="BOOTSTRAP_ADMIN_EMAIL"
    )
    bootstrap_admin_password: str = Field(
        "", validation_alias="BOOTSTRAP_ADMIN_PASSWORD"
    )
    secret_key: str = Field("", validation_alias="GATEWAY_SECRET_KEY")
    model_hidden_tools: list[str] = Field(
        default_factory=list, validation_alias="GATEWAY_MODEL_HIDDEN_TOOLS"
    )
    # -- Assessment demo mode ------------------------------------------------
    # Disabled unless BOTH the mode and the explicit acknowledgement are set.
    # It is meant for local/test deployments only; asking for it in a
    # production environment is a configuration error, not a silent default.
    demo_mode: bool = Field(False, validation_alias="GATEWAY_DEMO_MODE")
    demo_ack: bool = Field(False, validation_alias="GATEWAY_DEMO_ACK")
    demo_allow_remote: bool = Field(
        False, validation_alias="GATEWAY_DEMO_ALLOW_REMOTE"
    )
    demo_origins: str = Field("", validation_alias="GATEWAY_DEMO_ORIGINS")
    deployment_env: str = Field(
        "development", validation_alias="GATEWAY_DEPLOYMENT_ENV"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def demo_origin_list(self) -> list[str]:
        """Origins allowed to request a demo persona switch."""
        origins = [item.strip() for item in self.demo_origins.split(",") if item.strip()]
        for origin in self.cors_origin_list:
            if origin not in origins:
                origins.append(origin)
        return origins

    @property
    def is_production(self) -> bool:
        return self.deployment_env.strip().lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _validate_demo_mode(self) -> "GatewaySettings":
        if self.demo_mode and not self.demo_ack:
            raise ValueError(
                "GATEWAY_DEMO_MODE requires GATEWAY_DEMO_ACK=true to confirm "
                "this is an assessment deployment"
            )
        if self.demo_mode and self.is_production:
            raise ValueError(
                "GATEWAY_DEMO_MODE cannot be enabled when "
                "GATEWAY_DEPLOYMENT_ENV=production"
            )
        return self

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]

    @property
    def allowed_origin_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def allowed_upstream_host_list(self) -> list[str]:
        return [item.strip().lower() for item in self.allowed_upstream_hosts.split(",") if item.strip()]

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        if value and len(value) < 16:
            raise ValueError("GATEWAY_SECRET_KEY must be at least 16 characters")
        return value


class LlmSettings(_SectionSettings):
    """Gemini (Google AI) chat model settings for the chat agent.

    `api_key` is read from the environment only; YAML must never carry it.
    """

    _yaml_section_name: ClassVar[str] = "llm"

    provider: str = Field("google-genai", validation_alias="LLM_PROVIDER")
    model: str = Field("gemini-2.5-flash", validation_alias="GEMINI_MODEL")
    api_key: str = Field("", validation_alias="GEMINI_API_KEY")
    temperature: float = Field(
        0.2, ge=0.0, le=2.0, validation_alias="GEMINI_TEMPERATURE"
    )
    max_output_tokens: int = Field(
        2048, ge=128, le=65536, validation_alias="GEMINI_MAX_OUTPUT_TOKENS"
    )
    request_timeout_seconds: float = Field(
        30.0, gt=0, le=300, validation_alias="GEMINI_REQUEST_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(1, ge=0, le=5, validation_alias="GEMINI_MAX_RETRIES")

    @field_validator("api_key", "provider", "model")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class LangsmithSettings(_SectionSettings):
    """Optional LangSmith tracing. Disabled by default."""

    _yaml_section_name: ClassVar[str] = "langsmith"

    tracing_enabled: bool = Field(False, validation_alias="LANGSMITH_TRACING")
    project: str = Field("urumi-agent", validation_alias="LANGSMITH_PROJECT")
    api_key: str = Field("", validation_alias="LANGSMITH_API_KEY")
    endpoint: str = Field("", validation_alias="LANGSMITH_ENDPOINT")

    @field_validator("project", "api_key", "endpoint")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class AgentSettings(_SectionSettings):
    """Chat-agent runtime limits and gateway connection settings."""

    _yaml_section_name: ClassVar[str] = "agent"

    host: str = Field("0.0.0.0", validation_alias="AGENT_HOST")
    port: int = Field(8200, ge=1, le=65535, validation_alias="AGENT_PORT")
    gateway_mcp_url: str = Field(
        "http://localhost:8000/mcp", validation_alias="AGENT_GATEWAY_MCP_URL"
    )
    gateway_timeout_seconds: float = Field(
        20.0, gt=0, le=120, validation_alias="AGENT_GATEWAY_TIMEOUT_SECONDS"
    )
    max_iterations: int = Field(
        6, ge=1, le=20, validation_alias="AGENT_MAX_ITERATIONS"
    )
    max_tool_calls: int = Field(
        8, ge=1, le=50, validation_alias="AGENT_MAX_TOOL_CALLS"
    )
    max_history_messages: int = Field(
        20, ge=0, le=200, validation_alias="AGENT_MAX_HISTORY_MESSAGES"
    )
    max_message_chars: int = Field(
        8000, ge=256, le=100_000, validation_alias="AGENT_MAX_MESSAGE_CHARS"
    )
    tool_discovery_refresh_seconds: int = Field(
        30, ge=0, le=3600, validation_alias="AGENT_TOOL_REFRESH_SECONDS"
    )
    business_timezone: str = Field("UTC", validation_alias="AGENT_TIMEZONE")
    system_prompt_path: str = Field(
        "config/prompts/chat_agent.txt",
        validation_alias="AGENT_SYSTEM_PROMPT_PATH",
    )
    ephemeral_key_ttl_seconds: int = Field(
        180, ge=30, le=3600, validation_alias="AGENT_EPHEMERAL_KEY_TTL_SECONDS"
    )
    conversation_max_messages: int = Field(
        200, ge=10, le=5000, validation_alias="AGENT_CONVERSATION_MAX_MESSAGES"
    )
    cors_origins: str = Field(
        "http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="AGENT_CORS_ORIGINS",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @field_validator("gateway_mcp_url")
    @classmethod
    def _validate_gateway_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AGENT_GATEWAY_MCP_URL must be an absolute http(s) URL")
        return value


class AppSettings(BaseSettings):
    """Application settings for a single MCP service."""

    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    service_name: str = "urumi-mcp"
    host: str = Field("127.0.0.1", validation_alias="MCP_HOST")
    port: int = Field(8101, ge=1, le=65535, validation_alias="MCP_PORT")
    mcp_path: str = Field("/mcp", validation_alias="MCP_PATH")
    stateless_http: bool = Field(True, validation_alias="MCP_STATELESS_HTTP")
    json_response: bool = Field(True, validation_alias="MCP_JSON_RESPONSE")
    # DNS-rebinding protection: reject requests whose Host/Origin are not allowed.
    # Comma-separated; wildcard ports use the `host:*` form.
    allowed_hosts: str = Field("", validation_alias="MCP_ALLOWED_HOSTS")
    allowed_origins: str = Field("", validation_alias="MCP_ALLOWED_ORIGINS")
    enable_dns_rebinding_protection: bool = Field(
        True, validation_alias="MCP_ENABLE_DNS_REBINDING_PROTECTION"
    )
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    woocommerce: WooCommerceSettings = Field(default_factory=WooCommerceSettings)
    inventory: InventorySettings = Field(default_factory=InventorySettings)
    shipping: ShippingSettings = Field(default_factory=ShippingSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    langsmith: LangsmithSettings = Field(default_factory=LangsmithSettings)
    # Named `chat_agent` (not `agent`) to avoid clashing with the generic
    # `AGENT` environment variable some shells/CI set.
    chat_agent: AgentSettings = Field(default_factory=AgentSettings)

    @field_validator("mcp_path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("MCP_PATH must start with '/'")
        return value

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]

    @property
    def allowed_origin_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_data = _strip_none(_resolve_placeholders(load_yaml_config()))
        # Nested settings groups resolve their own section (see _SectionSettings).
        for nested in (
            "logging",
            "woocommerce",
            "inventory",
            "shipping_mock",
            "gateway",
            "llm",
            "langsmith",
            "agent",
        ):
            yaml_data.pop(nested, None)
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSource(settings_cls, yaml_data),
            file_secret_settings,
        )


def load_app_config(path: Path | None = None) -> dict[str, Any]:
    """Return the raw project YAML configuration (placeholders unresolved)."""
    return load_yaml_config(path)


def load_settings(
    service_name: str,
    *,
    default_port: int,
    default_path: str = "/mcp",
) -> AppSettings:
    """Build `AppSettings` for a service with service-scoped host/port.

    Both servers can run side by side: `WOOCOMMERCE_MCP_HOST` /
    `WOOCOMMERCE_MCP_PORT` and `INVENTORY_MCP_HOST` / `INVENTORY_MCP_PORT`
    take precedence, then the generic `MCP_HOST` / `MCP_PORT`.
    """
    prefix = service_name.upper().replace("-", "_")
    default_host = "0.0.0.0" if service_name == "gateway" else "127.0.0.1"
    host = os.environ.get(f"{prefix}_HOST") or os.environ.get("MCP_HOST") or default_host
    port = os.environ.get(f"{prefix}_PORT") or os.environ.get("MCP_PORT") or str(default_port)
    path = os.environ.get(f"{prefix}_PATH") or os.environ.get("MCP_PATH") or default_path
    return AppSettings(
        service_name=service_name,
        host=host,
        port=int(port),
        mcp_path=path,
    )


@lru_cache(maxsize=1)
def project_root() -> Path:
    return PROJECT_ROOT
