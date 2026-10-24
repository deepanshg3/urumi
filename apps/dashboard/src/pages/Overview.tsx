import { useEffect, useState } from "react";
import {
  Activity,
  Boxes,
  RefreshCw,
  Server,
  Sparkles,
  Wrench,
} from "lucide-react";

import { agentApi } from "../api";
import type { AgentConfig, Overview as OverviewData } from "../types";
import { Badge, Button, EmptyState, ErrorNotice, Panel, SkeletonRows } from "../components/ui";
import {
  formatLatency,
  formatRelative,
  formatTime,
  humanize,
  outcomeTone,
  serverTone,
} from "../lib/format";

interface OverviewProps {
  data: OverviewData | null;
  error: string | null;
  loading: boolean;
  onRefresh: () => void | Promise<void>;
  fullAccess: boolean;
}

export default function Overview({ data, error, loading, onRefresh, fullAccess }: OverviewProps) {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    agentApi
      .config()
      .then((value) => {
        if (!cancelled) setConfig(value);
      })
      .catch((err) => {
        if (!cancelled) setConfigError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error && !data) {
    return (
      <div className="page">
        <PageHeading onRefresh={onRefresh} loading={loading} />
        <ErrorNotice message={error} onRetry={() => void onRefresh()} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page">
        <PageHeading onRefresh={onRefresh} loading={loading} />
        <div className="panel">
          <SkeletonRows rows={4} columns={4} />
        </div>
      </div>
    );
  }

  const servers = data.servers;
  const healthy = servers.filter((server) => server.status === "healthy");
  const unhealthy = servers.filter((server) => server.status === "unhealthy");
  const disabled = servers.filter((server) => server.status === "disabled");
  const activity = data.recent_activity;
  const failures = activity.filter((entry) => entry.status !== "success");
  const lastActivity = activity[0] ?? null;

  return (
    <div className="page">
      <PageHeading onRefresh={onRefresh} loading={loading} />

      {error && <ErrorNotice message={error} tone="warn" />}

      <section className="stat-grid">
        <article className={`stat-card${unhealthy.length ? " is-error" : " is-accent"}`}>
          <div className="stat-card-head">
            <span className="stat-label">Upstreams</span>
            <span className="stat-icon">
              <Server aria-hidden="true" />
            </span>
          </div>
          <p className="stat-value">
            {healthy.length}
            <small> / {servers.length}</small>
          </p>
          <p className="stat-meta">
            {unhealthy.length > 0 ? (
              <Badge tone="error">{unhealthy.length} unreachable</Badge>
            ) : disabled.length > 0 ? (
              <Badge tone="warn">{disabled.length} disabled</Badge>
            ) : (
              <Badge tone="ok">All connected</Badge>
            )}
            <span>{data.upstreams_enabled} enabled</span>
          </p>
        </article>

        <article className="stat-card is-accent">
          <div className="stat-card-head">
            <span className="stat-label">Tools exposed</span>
            <span className="stat-icon">
              <Wrench aria-hidden="true" />
            </span>
          </div>
          <p className="stat-value">{data.tools_total}</p>
          <p className="stat-meta">
            <Badge tone="info">{data.tools_permitted} callable by you</Badge>
            {fullAccess && <span>full access</span>}
          </p>
        </article>

        <article className={`stat-card${failures.length ? " is-warn" : ""}`}>
          <div className="stat-card-head">
            <span className="stat-label">Recent activity</span>
            <span className="stat-icon">
              <Activity aria-hidden="true" />
            </span>
          </div>
          <p className="stat-value">{activity.length}</p>
          <p className="stat-meta">
            {failures.length > 0 ? (
              <Badge tone="warn">{failures.length} not successful</Badge>
            ) : (
              <Badge tone="ok">All successful</Badge>
            )}
            {lastActivity && <span>latest {formatRelative(lastActivity.created_at)}</span>}
          </p>
        </article>

        <article className="stat-card">
          <div className="stat-card-head">
            <span className="stat-label">Assistant</span>
            <span className="stat-icon">
              <Sparkles aria-hidden="true" />
            </span>
          </div>
          <p className="stat-value" style={{ fontSize: "var(--text-xl)" }}>
            {config ? config.model : "—"}
          </p>
          <p className="stat-meta">
            {configError ? (
              <Badge tone="error">Agent unreachable</Badge>
            ) : config ? (
              <>
                <Badge tone="neutral">tracing {config.tracing_enabled ? "on" : "off"}</Badge>
                <span>max {config.max_iterations} steps</span>
              </>
            ) : (
              <span>Connecting to the chat agent…</span>
            )}
          </p>
        </article>
      </section>

      <Panel
        title="Upstream health"
        description="Live connection state reported by the gateway aggregator."
        flush
      >
        {servers.length === 0 ? (
          <EmptyState
            icon={<Boxes aria-hidden="true" />}
            title="No upstream servers registered"
            description="Register an MCP server to expose its tools through the gateway."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Server</th>
                  <th>Status</th>
                  <th className="num">Tools</th>
                  <th>Last checked</th>
                  <th>Last error</th>
                </tr>
              </thead>
              <tbody>
                {servers.map((server) => (
                  <tr key={server.server_id}>
                    <td>
                      <div className="cell-primary">{server.name}</div>
                      <div className="cell-secondary mono">{server.server_id}</div>
                    </td>
                    <td>
                      <Badge tone={serverTone(server.status)} dot pulse={server.status === "healthy"}>
                        {humanize(server.status)}
                      </Badge>
                    </td>
                    <td className="num">{server.tool_count}</td>
                    <td className="text-muted">{formatRelative(server.last_checked_at)}</td>
                    <td className="text-muted" style={{ maxWidth: 320 }}>
                      {server.last_error ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Recent tool calls"
        description="The most recent authorized gateway calls, newest first."
        flush
        actions={
          activity.length > 0 ? (
            <Badge tone="neutral">{activity.length} shown</Badge>
          ) : undefined
        }
      >
        {activity.length === 0 ? (
          <EmptyState
            icon={<Activity aria-hidden="true" />}
            title="No tool calls yet"
            description="Once a user calls a tool through the gateway it is recorded here."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Tool</th>
                  <th>Server</th>
                  <th>Outcome</th>
                  <th className="num">Latency</th>
                </tr>
              </thead>
              <tbody>
                {activity.map((entry) => (
                  <tr key={entry.id}>
                    <td title={formatTime(entry.created_at)}>{formatRelative(entry.created_at)}</td>
                    <td>{entry.user_email ?? <span className="text-muted">API key</span>}</td>
                    <td className="mono">{entry.public_tool_name ?? "—"}</td>
                    <td className="text-muted">{entry.server_id}</td>
                    <td>
                      <Badge tone={outcomeTone(entry.status)} dot>
                        {humanize(entry.status)}
                      </Badge>
                      {entry.error_code && (
                        <div className="cell-secondary">{entry.error_code}</div>
                      )}
                    </td>
                    <td className="num">{formatLatency(entry.latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function PageHeading({
  onRefresh,
  loading,
}: {
  onRefresh: () => void | Promise<void>;
  loading: boolean;
}) {
  return (
    <header className="page-header">
      <div>
        <h2 className="page-title">Operational overview</h2>
        <p className="page-description">
          Live state of the Urumi gateway: connected MCP upstreams, the tools they expose and
          the calls your team has made.
        </p>
      </div>
      <div className="page-actions">
        <Button
          variant="secondary"
          onClick={() => void onRefresh()}
          icon={<RefreshCw aria-hidden="true" className={loading ? "spin" : undefined} />}
          disabled={loading}
        >
          Refresh
        </Button>
      </div>
    </header>
  );
}
