"""Unit tests for the gateway permission policy."""

from __future__ import annotations

from pathlib import Path

from services.gateway.policy import PermissionPolicy

YAML = """
roles:
  admin:
    permissions: ["tools:*", "gateway:audit:read"]
  member:
    permissions: []
grants:
  member:
    - "tools:woocommerce:list_products"
    - "tools:inventory:*"
deny:
  member:
    - "tools:shipping:*"
"""


def _policy(tmp_path: Path) -> PermissionPolicy:
    path = tmp_path / "permissions.yaml"
    path.write_text(YAML)
    return PermissionPolicy.load(path)


def test_admin_wildcard_allows_any_tool(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    permissions = policy.for_roles(["admin"])
    assert policy.can_call_tool(permissions, "shipping", "update_shipment_status")
    assert policy.can(permissions, "gateway:audit:read")


def test_member_gets_only_granted_tools(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    permissions = policy.for_roles(["member"])
    assert policy.can_call_tool(permissions, "woocommerce", "list_products")
    assert policy.can_call_tool(permissions, "inventory", "check_stock")
    assert not policy.can_call_tool(permissions, "woocommerce", "list_orders")
    assert not policy.can_call_tool(permissions, "shipping", "track_shipment")


def test_deny_wins_over_wildcard_grant(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    permissions = policy.for_roles(["member"])
    assert not policy.can_call_tool(permissions, "shipping", "track_shipment")


def test_multiple_roles_union_permissions(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    permissions = policy.for_roles(["member", "admin"])
    assert policy.can_call_tool(permissions, "shipping", "track_shipment")
    assert policy.can_call_tool(permissions, "woocommerce", "list_products")


def test_unknown_role_has_no_permissions(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    assert policy.for_roles(["ghost"]) == set()


def test_missing_file_yields_empty_policy(tmp_path: Path) -> None:
    policy = PermissionPolicy.load(tmp_path / "absent.yaml")
    assert policy.for_roles(["admin"]) == set()
    assert not policy.can_call_tool(set(), "woocommerce", "list_products")
