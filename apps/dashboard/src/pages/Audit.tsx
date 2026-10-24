import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ScrollText, Search } from "lucide-react";

import { api, ApiError } from "../api";
import type { AuditPage, Server } from "../types";
import { Badge, Button, EmptyState, ErrorNotice, Panel, SkeletonRows } from "../components/ui";
import { formatLatency, formatRelative, formatTime, humanize, outcomeTone } from "../lib/format";

const STATUSES = ["", "success", "denied", "error", "timeout"];

export default function Audit({ scopedToSelf = false }: { scopedToSelf?: boolean }) {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [server, setServer] = useState("");
  const [tool, setTool] = useState("");
  const [data, setData] = useState<AuditPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [servers, setServers] = useState<Server[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.audit({
        page,
        per_page: 25,
        status: status || undefined,
      });
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [page, status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .servers()
      .then((value) => setServers(value))
      .catch(() => setServers([]));
  }, []);

  const items = (data?.items ?? []).filter((entry) => {
    if (server && entry.server_id !== server) return false;
    const needle = tool.trim().toLowerCase();
    if (!needle) return true;
    return (
      (entry.public_tool_name ?? "").toLowerCase().includes(needle) ||
      (entry.upstream_tool_name ?? "").toLowerCase().includes(needle) ||
      (entry.user_email ?? "").toLowerCase().includes(needle)
    );
  });

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2 className="page-title">Audit log</h2>
          <p className="page-description">
            Every authorized tool call recorded by the gateway, including denied and failed calls.
            {scopedToSelf && " You are seeing your own activity only."}
          </p>
        </div>
        <div className="page-actions">
          {data && <Badge tone="neutral">{data.total} entries</Badge>}
        </div>
      </header>

      {error && <ErrorNotice message={error} onRetry={() => void load()} />}

      <Panel
        title="Filters"
        actions={
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setStatus("");
              setServer("");
              setTool("");
              setPage(1);
            }}
          >
            Clear
          </Button>
        }
      >
        <div className="form-row">
          <div className="field" style={{ flex: "0 1 180px" }}>
            <label className="field-label" htmlFor="audit-status">
              Outcome
            </label>
            <select
              id="audit-status"
              className="select"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
            >
              {STATUSES.map((value) => (
                <option key={value || "all"} value={value}>
                  {value ? humanize(value) : "All outcomes"}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ flex: "0 1 180px" }}>
            <label className="field-label" htmlFor="audit-server">
              Server
            </label>
            <select
              id="audit-server"
              className="select"
              value={server}
              onChange={(event) => {
                setServer(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All servers</option>
              {servers.map((item) => (
                <option key={item.server_id} value={item.server_id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ flex: "1 1 220px" }}>
            <label className="field-label" htmlFor="audit-tool">
              Tool or actor
            </label>
            <div className="search-field" style={{ maxWidth: "none" }}>
              <Search aria-hidden="true" />
              <input
                id="audit-tool"
                className="input"
                type="search"
                placeholder="woocommerce__list_products or user@…"
                value={tool}
                onChange={(event) => setTool(event.target.value)}
              />
            </div>
          </div>
        </div>
      </Panel>

      <Panel flush>
        {loading && !data ? (
          <SkeletonRows rows={6} columns={5} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<ScrollText aria-hidden="true" />}
            title="No audit entries match"
            description="Adjust the filters, or make a tool call to record a new entry."
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
                  <th>Auth</th>
                  <th>Outcome</th>
                  <th>Error</th>
                  <th className="num">Latency</th>
                </tr>
              </thead>
              <tbody>
                {items.map((entry) => (
                  <tr key={entry.id}>
                    <td title={formatTime(entry.created_at)}>{formatRelative(entry.created_at)}</td>
                    <td>
                      {entry.user_email ?? <span className="text-muted">API key</span>}
                    </td>
                    <td className="mono">
                      {entry.public_tool_name ?? entry.upstream_tool_name ?? "—"}
                    </td>
                    <td className="text-muted">{entry.server_id}</td>
                    <td className="text-muted">{entry.auth_method ?? "—"}</td>
                    <td>
                      <Badge tone={outcomeTone(entry.status)} dot>
                        {humanize(entry.status)}
                      </Badge>
                    </td>
                    <td className="text-muted">{entry.error_code ?? "—"}</td>
                    <td className="num">{formatLatency(entry.latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && (
          <div className="pagination">
            <span className="text-muted">
              Page {data.page} of {Math.max(1, Math.ceil(data.total / data.per_page))} ·{" "}
              {data.total} total
            </span>
            <div className="row-actions">
              <Button
                size="sm"
                variant="secondary"
                icon={<ChevronLeft aria-hidden="true" />}
                disabled={page <= 1 || loading}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={!data.has_more || loading}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
                <ChevronRight aria-hidden="true" />
              </Button>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
