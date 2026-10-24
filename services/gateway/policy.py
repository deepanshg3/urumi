"""Role/permission policy loaded from ``config/permissions.yaml``.

Deny rules always win. Tool permissions use the public gateway tool name form
``tools:<server_id>:<upstream_tool_name>`` so a member cannot call hidden or
unlisted tools by guessing a name.

The policy is evaluated per role: a permission is granted when *one* of the
caller's roles grants it and *that same role* does not deny it. A role that
denies a permission therefore blocks its own wildcards (``tools:shipping:*``
plus a deny on ``tools:shipping:create_shipment``) without cancelling a grant
that comes from a different role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PERMISSIONS_PATH = PROJECT_ROOT / "config" / "permissions.yaml"

# Gateway-management permissions (the `gateway:<area>:<action>` namespace).
GATEWAY_SERVERS_MANAGE = "gateway:servers:manage"
GATEWAY_KEYS_MANAGE = "gateway:keys:manage"
GATEWAY_KEYS_MANAGE_OWN = "gateway:keys:manage:own"
GATEWAY_KEYS_READ = "gateway:keys:read"
GATEWAY_USERS_MANAGE = "gateway:users:manage"
GATEWAY_AUDIT_READ = "gateway:audit:read"
GATEWAY_AUDIT_READ_ALL = "gateway:audit:read:all"
GATEWAY_TOOLS_READ = "gateway:tools:read"
GATEWAY_TOOLS_READ_ALL = "gateway:tools:read:all"

#: Every gateway-management permission the gateway knows about.
GATEWAY_PERMISSIONS = frozenset(
    {
        GATEWAY_SERVERS_MANAGE,
        GATEWAY_KEYS_MANAGE,
        GATEWAY_KEYS_MANAGE_OWN,
        GATEWAY_KEYS_READ,
        GATEWAY_USERS_MANAGE,
        GATEWAY_AUDIT_READ,
        GATEWAY_AUDIT_READ_ALL,
        GATEWAY_TOOLS_READ,
        GATEWAY_TOOLS_READ_ALL,
    }
)


class PermissionSet(frozenset):
    """The effective permissions of a user.

    Behaves like a ``frozenset`` of permission patterns and additionally
    remembers, per role, which patterns that role grants and which it denies.
    Keeping that detail lets :meth:`PermissionPolicy.can` apply deny rules
    per role instead of flattening them into a single set.
    """

    __slots__ = ("role_rules",)

    def __new__(
        cls,
        patterns: Iterable[str] = (),
        role_rules: Iterable[tuple[Iterable[str], Iterable[str]]] = (),
    ) -> "PermissionSet":
        obj = super().__new__(cls, patterns)
        obj.role_rules = tuple(
            (frozenset(granted), frozenset(denied)) for granted, denied in role_rules
        )
        return obj

    @property
    def patterns(self) -> frozenset[str]:
        return frozenset(self)


@dataclass(frozen=True)
class PermissionPolicy:
    roles: dict[str, set[str]] = field(default_factory=dict)
    grants: dict[str, set[str]] = field(default_factory=dict)
    deny: dict[str, set[str]] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "PermissionPolicy":
        source = path or DEFAULT_PERMISSIONS_PATH
        data: dict[str, Any] = {}
        if source.is_file():
            loaded = yaml.safe_load(source.read_text()) or {}
            if isinstance(loaded, dict):
                data = loaded
        roles = {
            name: set((body or {}).get("permissions") or [])
            for name, body in (data.get("roles") or {}).items()
        }
        grants = {
            name: set(values or []) for name, values in (data.get("grants") or {}).items()
        }
        deny = {
            name: set(values or []) for name, values in (data.get("deny") or {}).items()
        }
        descriptions = {
            name: str((body or {}).get("description") or "").strip()
            for name, body in (data.get("roles") or {}).items()
        }
        return cls(roles=roles, grants=grants, deny=deny, descriptions=descriptions)

    def role_names(self) -> set[str]:
        return set(self.roles) | set(self.grants) | set(self.deny)

    def for_roles(self, role_names: list[str]) -> PermissionSet:
        """Resolve the effective permissions for a set of role names.

        The returned set contains the granted permission patterns (useful for
        display) and keeps the per-role grant/deny detail used for checks.
        """
        patterns: set[str] = set()
        role_rules: list[tuple[frozenset[str], frozenset[str]]] = []
        for role in role_names:
            granted = set(self.roles.get(role, set())) | set(self.grants.get(role, set()))
            denied = frozenset(self.deny.get(role, set()))
            role_rules.append((frozenset(granted), denied))
            # A literal pattern that the role denies is dropped from the
            # advertised set; wildcard narrowing is handled by `can`.
            patterns |= {
                permission
                for permission in granted
                if not any(_matches(rule, permission) for rule in denied)
            }
        return PermissionSet(patterns, role_rules)

    def can(self, permissions: frozenset[str], required: str) -> bool:
        """Return whether ``required`` is granted by the caller's permissions."""
        role_rules = getattr(permissions, "role_rules", None)
        if role_rules:
            for granted, denied in role_rules:
                if not any(_matches(pattern, required) for pattern in granted):
                    continue
                if any(_matches(rule, required) for rule in denied):
                    continue
                return True
            return False
        return any(_matches(pattern, required) for pattern in permissions)

    def can_call_tool(
        self, permissions: frozenset[str], server_id: str, upstream_tool: str
    ) -> bool:
        required = f"tools:{server_id}:{upstream_tool}"
        return self.can(permissions, required)


def _matches(pattern: str, value: str) -> bool:
    if pattern == value == "*":
        return True
    return fnmatchcase(value, pattern)
