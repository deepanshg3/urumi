import { useCallback, useEffect, useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  KeyRound,
  LayoutDashboard,
  MessagesSquare,
  ScrollText,
  Server,
  Users,
  Wrench,
} from "lucide-react";

import { api, ApiError } from "./api";
import type { DemoConfig, DemoPersona, Overview as OverviewData, User } from "./types";
import { AppShell } from "./components/AppShell";
import type { NavEntry } from "./components/AppShell";
import { hasPermission, PERMISSIONS } from "./lib/permissions";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Chat from "./pages/Chat";
import Servers from "./pages/Servers";
import Tools from "./pages/Tools";
import Keys from "./pages/Keys";
import Audit from "./pages/Audit";
import UsersPage from "./pages/Users";
import PersonaSelect from "./pages/PersonaSelect";

type Tab = "overview" | "chat" | "servers" | "tools" | "keys" | "audit" | "users";

const NAV: { id: Tab; label: string; icon: LucideIcon; permission?: string }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "chat", label: "Chat", icon: MessagesSquare },
  { id: "servers", label: "MCP Servers", icon: Server, permission: PERMISSIONS.toolsRead },
  { id: "tools", label: "Tools", icon: Wrench, permission: PERMISSIONS.toolsRead },
  { id: "keys", label: "API Keys", icon: KeyRound, permission: PERMISSIONS.keysRead },
  { id: "audit", label: "Audit Log", icon: ScrollText, permission: PERMISSIONS.auditRead },
  { id: "users", label: "Users", icon: Users, permission: PERMISSIONS.usersManage },
];

const TAB_IDS = new Set<string>(NAV.map((item) => item.id));

function readTabFromHash(): Tab {
  const raw = window.location.hash.replace(/^#\/?/, "").trim();
  return TAB_IDS.has(raw) ? (raw as Tab) : "overview";
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [demo, setDemo] = useState<DemoConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [tab, setTab] = useState<Tab>(readTabFromHash);
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);

  const loadMe = useCallback(async (): Promise<User | null> => {
    try {
      const me = await api.me();
      setUser(me);
      return me;
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) {
        console.error(error);
      }
      setUser(null);
      return null;
    }
  }, []);

  const loadEntry = useCallback(async () => {
    const [configResult, meResult] = await Promise.allSettled([api.demo(), api.me()]);
    if (configResult.status === "fulfilled" && configResult.value.enabled) {
      setDemo(configResult.value);
    } else {
      setDemo(null);
    }
    if (meResult.status === "fulfilled") {
      setUser(meResult.value);
      setPickerOpen(false);
    } else {
      if (
        meResult.status === "rejected" &&
        (!(meResult.reason instanceof ApiError) || meResult.reason.status !== 401)
      ) {
        console.error(meResult.reason);
      }
      setUser(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadEntry();
  }, [loadEntry]);

  useEffect(() => {
    const onHashChange = () => setTab(readTabFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setOverview(null);
      setPickerOpen(false);
      setSwitchError("Your session ended. Choose a persona to continue.");
      void api
        .demo()
        .then(setDemo)
        .catch(() => setDemo(null));
    };
    window.addEventListener("urumi:unauthorized", onUnauthorized);
    return () => window.removeEventListener("urumi:unauthorized", onUnauthorized);
  }, []);

  const loadOverview = useCallback(async () => {
    setOverviewLoading(true);
    try {
      setOverview(await api.overview());
      setOverviewError(null);
    } catch (error) {
      // The top bar simply reports an unknown state; pages show their own errors.
      setOverview(null);
      setOverviewError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!user) {
      setOverview(null);
      return;
    }
    void loadOverview();
    const timer = window.setInterval(() => void loadOverview(), 60_000);
    const onFocus = () => void loadOverview();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [user, epoch, loadOverview]);

  const enterPersona = useCallback(
    async (persona: DemoPersona) => {
      setSwitchError(null);
      setSwitching(persona.id);
      try {
        const result = await api.demoSession(persona.id);
        setUser(result.user);
        setPickerOpen(false);
        setOverview(null);
        setEpoch((value) => value + 1);
      } catch (error) {
        setSwitchError(error instanceof ApiError ? error.message : String(error));
        // A failed switch may already have revoked the previous session, so
        // trust the server rather than the role we were displaying.
        const current = await loadMe();
        if (!current) {
          try {
            setDemo(await api.demo());
          } catch {
            setDemo(null);
          }
        }
        setPickerOpen(true);
      } finally {
        setSwitching(null);
      }
    },
    [loadMe],
  );

  const refreshDashboard = useCallback(async () => {
    setRefreshing(true);
    try {
      const current = await loadMe();
      if (!current) {
        setOverview(null);
        setSwitchError("Your session ended. Choose a persona to continue.");
        try {
          setDemo(await api.demo());
        } catch {
          // keep the existing config; the entry screen will show the error
        }
        return;
      }
      setEpoch((value) => value + 1);
      await loadOverview();
    } finally {
      setRefreshing(false);
    }
  }, [loadMe, loadOverview]);

  const canManageServers = hasPermission(user, PERMISSIONS.serversManage);
  const canManageUsers = hasPermission(user, PERMISSIONS.usersManage);
  const canCreateKeys =
    hasPermission(user, PERMISSIONS.keysManage) ||
    hasPermission(user, PERMISSIONS.keysManageOwn);
  const canReadAllTools = hasPermission(user, PERMISSIONS.toolsReadAll);

  const nav = useMemo<NavEntry[]>(
    () =>
      NAV.map((entry) => ({
        id: entry.id,
        label: entry.label,
        icon: entry.icon,
        permission: entry.permission,
        badge:
          entry.id === "tools" && overview ? overview.tools_total : entry.id === "servers" && overview ? overview.servers.length : null,
      })),
    [overview],
  );

  const activeTab = useMemo<Tab>(() => {
    const entry = NAV.find((item) => item.id === tab);
    if (entry?.permission && !hasPermission(user, entry.permission)) return "overview";
    return tab;
  }, [tab, user]);

  useEffect(() => {
    if (activeTab !== tab) {
      setTab("overview");
      window.location.hash = "#/overview";
    }
  }, [activeTab, tab]);

  async function logout() {
    try {
      await api.logout();
    } catch {
      // ignore: session may already be gone
    }
    setUser(null);
    setOverview(null);
    setPickerOpen(false);
    setSwitchError(null);
    await loadEntry();
  }

  const currentPersona = useMemo(() => {
    if (!demo || !user) return null;
    return (
      demo.personas.find((persona) => persona.email === user.email) ??
      demo.personas.find((persona) => user.roles.includes(persona.role)) ??
      null
    );
  }, [demo, user]);

  if (loading) {
    return (
      <div className="state-block" style={{ minHeight: "100vh" }}>
        <div className="state-icon">
          <span className="spinner" aria-hidden="true" />
        </div>
        <p className="state-text">Loading Urumi…</p>
      </div>
    );
  }

  if (!user) {
    if (demo?.enabled) {
      return (
        <PersonaSelect
          personas={demo.personas}
          onSelect={(persona) => void enterPersona(persona)}
          busy={switching}
          error={switchError}
          deployment={demo.deployment}
          onRefreshConfig={() => void loadEntry()}
        />
      );
    }
    return <Login onLoggedIn={setUser} />;
  }

  if (pickerOpen && demo?.enabled) {
    return (
      <PersonaSelect
        personas={demo.personas}
        onSelect={(persona) => void enterPersona(persona)}
        busy={switching}
        error={switchError}
        deployment={demo.deployment}
        current={currentPersona?.id}
        onCancel={() => {
          setPickerOpen(false);
          setSwitchError(null);
        }}
      />
    );
  }

  return (
    <AppShell
      user={user}
      nav={nav}
      active={activeTab}
      contentKey={epoch}
      onSelect={(id) => {
        const next = id as Tab;
        setTab(next);
        window.location.hash = `#/${next}`;
      }}
      onLogout={() => void logout()}
      overview={overview}
      demo={
        demo?.enabled && currentPersona
          ? {
              personas: demo.personas,
              current: currentPersona.id,
              busy: switching !== null,
              refreshing,
              onSelect: (id) => {
                const persona = demo.personas.find((item) => item.id === id);
                if (persona && persona.id !== currentPersona.id) {
                  void enterPersona(persona);
                }
              },
              onOpenPicker: () => setPickerOpen(true),
              onRefresh: () => void refreshDashboard(),
            }
          : undefined
      }
    >
      {activeTab === "overview" && (
        <Overview
          data={overview}
          error={overviewError}
          loading={overviewLoading}
          onRefresh={loadOverview}
          fullAccess={canReadAllTools}
        />
      )}
      {activeTab === "chat" && <Chat />}
      {activeTab === "servers" && <Servers canManage={canManageServers} />}
      {activeTab === "tools" && <Tools />}
      {activeTab === "keys" && <Keys canCreate={canCreateKeys} />}
      {activeTab === "audit" && <Audit scopedToSelf={!hasPermission(user, PERMISSIONS.auditReadAll)} />}
      {activeTab === "users" && canManageUsers && <UsersPage canManageUsers={canManageUsers} />}
    </AppShell>
  );
}
