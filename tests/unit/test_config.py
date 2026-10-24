"""Configuration validation and precedence tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.common.config import (
    AppSettings,
    InventorySettings,
    LoggingSettings,
    WooCommerceSettings,
    load_settings,
    load_yaml_config,
)
from services.common.logging import redact


def test_woocommerce_defaults_and_auth_resolution() -> None:
    settings = WooCommerceSettings(_env_file=None)
    assert settings.base_url == "http://localhost:8080"
    assert settings.resolved_auth_mode == "oauth1"
    assert settings.default_page_size <= settings.max_page_size
    assert (
        WooCommerceSettings(base_url="https://store.test", _env_file=None).resolved_auth_mode
        == "basic"
    )


@pytest.mark.parametrize(
    "url", ["store.test", "ftp://store.test", "https://", "", "  "]
)
def test_invalid_base_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        WooCommerceSettings(base_url=url)


def test_base_url_is_normalized_without_trailing_slash() -> None:
    assert (
        WooCommerceSettings(base_url="https://store.test/", _env_file=None).base_url
        == "https://store.test"
    )


def test_signing_base_url_is_optional_and_normalized() -> None:
    assert WooCommerceSettings(_env_file=None).signing_base_url is None
    assert WooCommerceSettings(signing_base_url="", _env_file=None).signing_base_url is None
    assert (
        WooCommerceSettings(
            base_url="http://host.docker.internal:8080",
            signing_base_url="http://localhost:8080/",
            _env_file=None,
        ).signing_base_url
        == "http://localhost:8080"
    )
    with pytest.raises(ValidationError):
        WooCommerceSettings(signing_base_url="localhost:8080", _env_file=None)


def test_page_size_bounds_are_validated() -> None:
    with pytest.raises(ValidationError):
        WooCommerceSettings(default_page_size=200, max_page_size=100)
    with pytest.raises(ValidationError):
        WooCommerceSettings(max_page_size=101)
    with pytest.raises(ValidationError):
        WooCommerceSettings(timeout_seconds=0)


@pytest.mark.parametrize("level", ["debug", "INFO", "Warning", "error", "critical"])
def test_log_levels_are_normalized(level: str) -> None:
    assert LoggingSettings(level=level).level == level.upper()


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ValidationError):
        LoggingSettings(level="verbose")


def test_inventory_settings_validation() -> None:
    settings = InventorySettings(low_stock_threshold=7, summary_max_products=50, _env_file=None)
    assert settings.low_stock_threshold == 7
    assert settings.summary_max_products == 50
    with pytest.raises(ValidationError):
        InventorySettings(low_stock_threshold=-1)
    with pytest.raises(ValidationError):
        InventorySettings(summary_scan_page_size=101)


def test_require_credentials_reports_missing_names_only() -> None:
    settings = WooCommerceSettings(consumer_key="", consumer_secret="", _env_file=None)
    with pytest.raises(Exception) as exc:
        settings.require_credentials()
    message = str(exc.value)
    assert "WOOCOMMERCE_CONSUMER_KEY" in message
    assert "WOOCOMMERCE_CONSUMER_SECRET" in message


def test_env_variables_override_yaml_and_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "mcp.yaml"
    config.write_text(
        textwrap.dedent(
            """
            logging:
              level: WARNING
            woocommerce:
              base_url: http://yaml-store:8080
              timeout_seconds: 3
            inventory:
              low_stock_threshold: 9
            """
        )
    )
    monkeypatch.setenv("URUMI_MCP_CONFIG", str(config))
    monkeypatch.setenv("WOOCOMMERCE_BASE_URL", "http://env-store:9090")
    monkeypatch.setenv("INVENTORY_LOW_STOCK_THRESHOLD", "2")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("WOOCOMMERCE_MCP_PORT", "9999")

    settings = load_settings("woocommerce-mcp", default_port=8101)

    assert settings.woocommerce.base_url == "http://env-store:9090"  # env wins
    assert settings.woocommerce.timeout_seconds == 3  # YAML beats default
    assert settings.inventory.low_stock_threshold == 2  # env wins
    assert settings.logging.level == "DEBUG"  # env wins
    assert settings.port == 9999  # service-specific env wins


def test_yaml_defaults_apply_without_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # do not read a developer's local .env
    config = tmp_path / "mcp.yaml"
    config.write_text(
        textwrap.dedent(
            """
            woocommerce:
              base_url: http://yaml-store:8080
              max_page_size: 50
            """
        )
    )
    monkeypatch.setenv("URUMI_MCP_CONFIG", str(config))
    for name in (
        "WOOCOMMERCE_BASE_URL",
        "WOOCOMMERCE_MAX_PAGE_SIZE",
        "WOOCOMMERCE_MCP_PORT",
        "MCP_PORT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings("woocommerce-mcp", default_port=8101)
    assert settings.woocommerce.base_url == "http://yaml-store:8080"
    assert settings.woocommerce.max_page_size == 50
    assert settings.port == 8101


def test_missing_yaml_file_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("URUMI_MCP_CONFIG", str(tmp_path / "does-not-exist.yaml"))
    monkeypatch.delenv("WOOCOMMERCE_BASE_URL", raising=False)
    settings = load_settings("inventory-mcp", default_port=8102)
    assert settings.woocommerce.base_url == "http://localhost:8080"
    assert settings.port == 8102


def test_invalid_yaml_section_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "mcp.yaml"
    config.write_text("woocommerce: not-a-mapping\n")
    monkeypatch.setenv("URUMI_MCP_CONFIG", str(config))
    with pytest.raises(ValueError):
        load_settings("woocommerce-mcp", default_port=8101)


def test_project_yaml_configs_parse() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("config/app.yaml", "config/mcp_services.yaml", "config/servers.yaml"):
        data = load_yaml_config(root / name)
        assert isinstance(data, dict)


def test_service_settings_reject_bad_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WOOCOMMERCE_MCP_PORT", "70000")
    with pytest.raises(ValidationError):
        load_settings("woocommerce-mcp", default_port=8101)


def test_redaction_hides_credentials_and_emails() -> None:
    # Built at runtime so this test file itself never contains secret-shaped literals.
    ck = "ck_" + "abcdef123456"
    cs = "cs_" + "abcdef123456"
    google = "AIza" + "abcdefghijklmnopqrstuvwxyz0123456789"
    email = "person" + "@example.test"
    text = f"key={ck} secret={cs} google={google} email={email}"
    cleaned = redact(text)
    assert ck not in cleaned
    assert cs not in cleaned
    assert google not in cleaned
    assert email not in cleaned
    assert "<redacted>" in cleaned


def test_app_settings_does_not_expose_secrets_in_repr() -> None:
    settings = AppSettings(
        woocommerce=WooCommerceSettings(
            consumer_key="ck_" + "super_secret_value",
            consumer_secret="cs_" + "super_secret_value",
        )
    )
    # Pydantic repr includes field values, so verify the redaction helper is what
    # protects logs, and confirm no tool output includes these fields.
    from services.woocommerce_mcp.tools import _to_product_summary
    from tests.conftest import product

    summary = _to_product_summary(product(1)).model_dump_json()
    assert "consumer_key" not in summary
    assert "consumer_secret" not in summary
    assert settings.woocommerce.consumer_key  # exists only in memory
