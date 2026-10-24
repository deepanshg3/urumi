import type { User } from "../types";

/**
 * Gateway-management permissions, mirroring `config/permissions.yaml`.
 * The dashboard never decides access on its own: these flags only hide UI
 * that the gateway would refuse anyway. The gateway remains the authority.
 */
export const PERMISSIONS = {
  serversManage: "gateway:servers:manage",
  keysManage: "gateway:keys:manage",
  keysManageOwn: "gateway:keys:manage:own",
  keysRead: "gateway:keys:read",
  usersManage: "gateway:users:manage",
  auditRead: "gateway:audit:read",
  auditReadAll: "gateway:audit:read:all",
  toolsRead: "gateway:tools:read",
  toolsReadAll: "gateway:tools:read:all",
} as const;

export function hasPermission(user: User | null | undefined, permission: string): boolean {
  if (!user) return false;
  return (user.permissions ?? []).includes(permission);
}

/** True when the account may administer the gateway itself (users, servers, keys). */
export function canAdminister(user: User | null | undefined): boolean {
  return (
    hasPermission(user, PERMISSIONS.usersManage) ||
    hasPermission(user, PERMISSIONS.serversManage)
  );
}

export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  member: "Operator",
  viewer: "Viewer",
};

export const ROLE_DESCRIPTIONS: Record<string, string> = {
  admin: "Full tool access plus gateway administration",
  member: "Store operations: reads plus shipment status updates",
  viewer: "Read-only: no changes, no key management",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
