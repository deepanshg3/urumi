"""Pass 0 foundation checks: structure, config integrity, dependency imports."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "AGENTS.md",
    "README.md",
    ".gitignore",
    ".env.example",
    "pyproject.toml",
    "config/app.yaml",
    "config/servers.yaml",
    "config/permissions.yaml",
    "config/prompts/chat_agent.txt",
    "apps/dashboard",
    "services/gateway",
    "services/woocommerce_mcp",
    "services/inventory_mcp",
    "services/shipping_mcp",
    "tests",
    "deploy/docker",
    "deploy/helm",
    "docs/architecture.md",
    "docs/implementation-plan.md",
    "docs/threat-model.md",
]

REQUIRED_ENV_KEYS = [
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "LANGSMITH_API_KEY",
    "LANGSMITH_TRACING",
    "LANGSMITH_PROJECT",
    "DATABASE_URL",
    "WOOCOMMERCE_BASE_URL",
    "WOOCOMMERCE_CONSUMER_KEY",
    "WOOCOMMERCE_CONSUMER_SECRET",
]

# Values that would indicate a real credential slipped into a tracked file.
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),          # Google API key
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),           # common secret-key prefix
    re.compile(r"cs_[A-Za-z0-9]{12,}"),              # WooCommerce consumer secret
    re.compile(r"ck_[A-Za-z0-9]{12,}"),              # WooCommerce consumer key
]


def test_repository_structure_exists() -> None:
    missing = [p for p in REQUIRED_PATHS if not (ROOT / p).exists()]
    assert not missing, f"missing required paths: {missing}"


def test_env_example_has_all_required_keys() -> None:
    content = (ROOT / ".env.example").read_text()
    keys = {
        line.split("=", 1)[0].strip()
        for line in content.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    missing = [k for k in REQUIRED_ENV_KEYS if k not in keys]
    assert not missing, f".env.example missing keys: {missing}"


def test_env_example_contains_only_placeholders() -> None:
    content = (ROOT / ".env.example").read_text()
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(content), f"possible real secret in .env.example: {pattern.pattern}"


def test_gitignore_excludes_env_and_venv() -> None:
    content = (ROOT / ".gitignore").read_text()
    assert ".env" in content
    assert ".venv/" in content


@pytest.mark.parametrize(
    "name", ["config/app.yaml", "config/servers.yaml", "config/permissions.yaml"]
)
def test_config_yaml_parses(name: str) -> None:
    data = yaml.safe_load((ROOT / name).read_text())
    assert isinstance(data, dict) and data, f"{name} must parse to a non-empty mapping"


def test_servers_yaml_declares_three_upstream_servers() -> None:
    data = yaml.safe_load((ROOT / "config/servers.yaml").read_text())
    ids = {s["id"] for s in data["servers"]}
    assert ids == {"woocommerce", "inventory", "shipping"}


def test_permissions_yaml_defines_roles() -> None:
    data = yaml.safe_load((ROOT / "config/permissions.yaml").read_text())
    assert {"admin", "member"} <= set(data["roles"])


# Gitignored local-only files that may legitimately hold development credentials.
LOCAL_SECRET_FILES = {".env", "deploy/docker/woocommerce/.env"}


def test_no_secrets_in_tracked_text_files() -> None:
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in skip_dirs for part in path.parts):
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.name in {".env.example", "test_pass0_foundation.py"}:
            continue
        if relative in LOCAL_SECRET_FILES:
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{relative}: {pattern.pattern}")
    assert not offenders, f"possible secrets found: {offenders}"


def test_core_dependencies_import() -> None:
    for module in (
        "mcp",
        "fastapi",
        "uvicorn",
        "langchain",
        "langchain_google_genai",
        "langsmith",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
        "yaml",
        "pytest",
    ):
        __import__(module)


def test_pyproject_declares_required_dependencies() -> None:
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = " ".join(data["project"]["dependencies"]).lower()
    for name in (
        "mcp",
        "fastapi",
        "uvicorn",
        "langchain",
        "langchain-google-genai",
        "langsmith",
        "pydantic",
        "pydantic-settings",
        "sqlalchemy",
        "pyyaml",
    ):
        assert name in deps, f"pyproject.toml missing dependency: {name}"
    dev = " ".join(data["project"]["optional-dependencies"]["dev"]).lower()
    assert "pytest" in dev


def test_env_files_are_gitignored() -> None:
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in ignored
    for relative in LOCAL_SECRET_FILES:
        assert relative.split("/")[-1] == ".env"
    # A local .env may exist for development, but must never be tracked.
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", ".env", "deploy/docker/woocommerce/.env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert tracked == "", f"secret files are tracked by git: {tracked}"


def test_pass_statuses_are_recorded() -> None:
    plan = (ROOT / "docs/implementation-plan.md").read_text()
    headings = {
        int(match.group(1)): match.group(2)
        for line in plan.splitlines()
        if (match := re.match(r"## Pass (\d+) — (.*)", line))
    }
    for n in range(0, 11):
        assert n in headings, f"implementation plan missing Pass {n}"
    for n in range(0, 11):
        assert "complete" in headings[n].lower(), f"Pass {n} must be marked complete"


def test_all_services_are_implemented() -> None:
    for service in ("woocommerce_mcp", "inventory_mcp", "shipping_mcp", "gateway"):
        directory = ROOT / "services" / service
        files = [
            p
            for p in directory.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        ]
        assert files, f"services/{service} should contain code"
        assert any(p.suffix == ".py" for p in files), (
            f"services/{service} must have Python code, found: {[p.name for p in files]}"
        )


def test_implemented_services_have_code_and_tests() -> None:
    expected = {
        "woocommerce_mcp": "test_woocommerce_tools.py",
        "inventory_mcp": "test_inventory_tools.py",
        "shipping_mcp": "test_shipping_tools.py",
        "gateway": "test_gateway_mcp.py",
    }
    entrypoints = {"gateway": "app.py"}
    for service, test_file in expected.items():
        entrypoint = entrypoints.get(service, "server.py")
        assert (ROOT / "services" / service / entrypoint).is_file()
        assert (ROOT / "tests" / "unit" / test_file).is_file()
