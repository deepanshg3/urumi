import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  ArrowLeftRight,
  ChevronLeft,
  ChevronRight,
  LogOut,
  Menu,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";

import type { DemoPersona, Overview as OverviewData, User } from "../types";
import { initials } from "../lib/format";
import { hasPermission, roleLabel } from "../lib/permissions";
import { BrandMark } from "./BrandMark";
import { Button } from "./ui";

export interface NavEntry {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Gateway permission required to see this entry. */
  permission?: string;
  badge?: string | number | null;
}

export interface DemoControls {
  personas: DemoPersona[];
  current: string;
  busy: boolean;
  refreshing: boolean;
  onSelect: (id: string) => void;
  onOpenPicker: () => void;
  onRefresh: () => void;
}

interface AppShellProps {
  user: User;
  nav: NavEntry[];
  active: string;
  onSelect: (id: string) => void;
  onLogout: () => void;
  overview: OverviewData | null;
  demo?: DemoControls;
  /** Bumped whenever role-sensitive pages must remount and refetch. */
  contentKey?: number;
  children: React.ReactNode;
}

function HealthPill({ overview }: { overview: OverviewData | null }) {
  if (!overview) {
    return (
      <span className="badge badge-neutral" title="Gateway status unknown">
        <span className="badge-dot" />
        Connecting
      </span>
    );
  }
  const servers = overview.servers;
  const healthy = servers.filter((server) => server.status === "healthy").length;
  const degraded = servers.filter((server) => server.status === "unhealthy").length;
  const disabled = servers.filter((server) => server.status === "disabled").length;

  if (servers.length === 0) {
    return (
      <span className="badge badge-neutral">
        <span className="badge-dot" />
        No upstreams
      </span>
    );
  }
  if (degraded > 0) {
    return (
      <span className="badge badge-error" title={`${degraded} upstream(s) unreachable`}>
        <span className="badge-dot" />
        {degraded} upstream degraded
      </span>
    );
  }
  if (healthy < servers.length && disabled > 0) {
    return (
      <span className="badge badge-warn" title={`${disabled} upstream(s) disabled`}>
        <span className="badge-dot" />
        {healthy}/{servers.length} upstreams
      </span>
    );
  }
  return (
    <span className="badge badge-ok" title="All upstreams healthy">
      <span className="badge-dot" />
      All systems operational
    </span>
  );
}

export function AppShell({
  user,
  nav,
  active,
  onSelect,
  onLogout,
  overview,
  demo,
  contentKey,
  children,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem("urumi.sidebar.collapsed");
    if (stored === "1") setCollapsed(true);
  }, []);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const visibleNav = nav.filter(
    (entry) => !entry.permission || hasPermission(user, entry.permission),
  );
  const activeEntry = visibleNav.find((entry) => entry.id === active);
  const persona = demo?.personas.find((item) => item.id === demo.current) ?? null;

  return (
    <div className={`app-shell${collapsed ? " is-collapsed" : ""}${drawerOpen ? " is-drawer-open" : ""}`}>
      {drawerOpen && (
        <button
          type="button"
          className="drawer-scrim"
          aria-label="Close navigation"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      <aside className="sidebar" aria-label="Primary">
        <a className="brand" href="#main">
          <span className="brand-mark">
            <BrandMark size={20} />
          </span>
          <span className="brand-text">
            <span className="brand-name">Urumi</span>
            <span className="brand-sub">MCP Gateway</span>
          </span>
        </a>

        <nav className="sidebar-nav">
          <span className="sidebar-section-label">Workspace</span>
          {visibleNav.map((entry) => {
            const Icon = entry.icon;
            const isActive = entry.id === active;
            return (
              <button
                key={entry.id}
                type="button"
                className={`nav-item${isActive ? " is-active" : ""}`}
                aria-current={isActive ? "page" : undefined}
                title={collapsed ? entry.label : undefined}
                onClick={() => {
                  onSelect(entry.id);
                  setDrawerOpen(false);
                }}
              >
                <Icon aria-hidden="true" />
                <span className="nav-item-label">{entry.label}</span>
                {entry.badge !== null && entry.badge !== undefined && (
                  <span className="nav-count">{entry.badge}</span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="user-chip">
            <span className="avatar" aria-hidden="true">
              {initials(user.display_name || user.email, user.email)}
            </span>
            <span className="user-chip-text">
              <span className="user-chip-name">{user.display_name || user.email}</span>
              <span className="user-chip-role">
                {user.roles.map(roleLabel).join(", ") || "no role"}
              </span>
            </span>
          </div>
          <button type="button" className="nav-item" onClick={onLogout}>
            <LogOut aria-hidden="true" />
            <span className="nav-item-label">Sign out</span>
          </button>
        </div>
      </aside>

      <div className="content">
        <header className="topbar">
          <button
            type="button"
            className="icon-button sidebar-toggle"
            aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen((open) => !open)}
          >
            {drawerOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </button>

          <div className="topbar-titles">
            <h1 className="topbar-title">{activeEntry?.label ?? "Urumi"}</h1>
            <p className="topbar-subtitle">Urumi MCP Gateway · team commerce operations</p>
          </div>

          <div className="topbar-actions">
            {demo && persona && (
              <div className="persona-switcher">
                <span className="demo-flag" title="Assessment demo mode">
                  <ShieldAlert aria-hidden="true" />
                  DEMO
                </span>
                <select
                  className="persona-select"
                  aria-label="Current demo persona"
                  value={demo.current}
                  disabled={demo.busy}
                  onChange={(event) => demo.onSelect(event.target.value)}
                >
                  {demo.personas.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title} · {item.role}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <HealthPill overview={overview} />
            <button
              type="button"
              className="icon-button desktop-collapse"
              aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
              onClick={() => {
                setCollapsed((value) => {
                  window.localStorage.setItem("urumi.sidebar.collapsed", value ? "0" : "1");
                  return !value;
                });
              }}
            >
              {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronLeft aria-hidden="true" />}
            </button>
          </div>
        </header>

        {demo && persona && (
          <div className="demo-banner" role="note">
            <span className="demo-flag">
              <ShieldAlert aria-hidden="true" />
              ASSESSMENT DEMO
            </span>
            <span className="demo-banner-text">
              Acting as <strong>{persona.title}</strong> with the{" "}
              <code>{persona.role}</code> role. Demo mode is not production
              authentication.
            </span>
            <div className="demo-banner-actions">
              <Button
                size="sm"
                variant="secondary"
                icon={<ArrowLeftRight aria-hidden="true" />}
                onClick={demo.onOpenPicker}
                disabled={demo.busy}
              >
                Switch persona
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon={<RefreshCw className={demo.refreshing ? "spin" : undefined} aria-hidden="true" />}
                onClick={demo.onRefresh}
                disabled={demo.refreshing || demo.busy}
              >
                {demo.refreshing ? "Refreshing…" : "Refresh data"}
              </Button>
            </div>
          </div>
        )}

        <main id="main" key={contentKey}>
          {children}
        </main>
      </div>
    </div>
  );
}
