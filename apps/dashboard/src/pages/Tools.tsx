import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Lock, Search, ShieldCheck, Wrench } from "lucide-react";

import { api, ApiError } from "../api";
import type { Tool } from "../types";
import { Badge, Button, EmptyState, ErrorNotice, Panel, SkeletonRows } from "../components/ui";

export default function Tools() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [server, setServer] = useState("");

  const load = () => {
    setLoading(true);
    api
      .tools()
      .then((value) => {
        setTools(value);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const servers = useMemo(
    () => Array.from(new Set(tools.map((tool) => tool.server_id))).sort(),
    [tools],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return tools.filter((tool) => {
      if (server && tool.server_id !== server) return false;
      if (!needle) return true;
      return (
        tool.name.toLowerCase().includes(needle) ||
        tool.upstream_tool.toLowerCase().includes(needle) ||
        tool.server_id.toLowerCase().includes(needle) ||
        (tool.description ?? "").toLowerCase().includes(needle)
      );
    });
  }, [tools, query, server]);

  const permittedCount = filtered.filter((tool) => tool.permitted).length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2 className="page-title">Tools</h2>
          <p className="page-description">
            Every tool the gateway discovered, namespaced by server. Tools you are not permitted to
            call remain listed but are refused by the gateway on every attempt.
          </p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={load}>
            Reload
          </Button>
        </div>
      </header>

      {error && <ErrorNotice message={error} onRetry={load} />}

      <Panel
        title={`${filtered.length} tool${filtered.length === 1 ? "" : "s"}`}
        description={`${permittedCount} callable with your current role.`}
        actions={
          <div className="toolbar">
            <div className="search-field">
              <Search aria-hidden="true" />
              <input
                className="input"
                type="search"
                placeholder="Search tools…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search tools"
              />
            </div>
            <select
              className="select"
              value={server}
              onChange={(event) => setServer(event.target.value)}
              aria-label="Filter by server"
              style={{ width: "auto", minWidth: 170 }}
            >
              <option value="">All servers</option>
              {servers.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        }
        flush
      >
        {loading ? (
          <SkeletonRows rows={5} columns={3} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Wrench aria-hidden="true" />}
            title={tools.length === 0 ? "No tools discovered" : "No tool matches your filters"}
            description={
              tools.length === 0
                ? "Tools appear once an upstream server is reachable and has been aggregated."
                : "Try a different search term or server filter."
            }
            action={
              tools.length > 0 ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setQuery("");
                    setServer("");
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="tool-list">
            {filtered.map((tool) => (
              <div className="tool-row" key={tool.name}>
                <div>
                  <div className="tool-name">{tool.name}</div>
                  <div className="tool-server">
                    {tool.server_id} · upstream <code>{tool.upstream_tool}</code>
                  </div>
                </div>
                <div>
                  <p className="tool-description">{tool.description ?? "No description provided."}</p>
                  <details>
                    <summary
                      style={{
                        cursor: "pointer",
                        fontSize: "var(--text-xs)",
                        color: "var(--text-secondary)",
                        marginTop: "var(--space-2)",
                      }}
                    >
                      Input schema
                    </summary>
                    <pre className="tool-schema">{JSON.stringify(tool.input_schema, null, 2)}</pre>
                  </details>
                </div>
                <div>
                  {tool.permitted ? (
                    <Badge tone="ok">
                      <ShieldCheck aria-hidden="true" /> You may call
                    </Badge>
                  ) : (
                    <Badge tone="neutral">
                      <Lock aria-hidden="true" /> Not permitted
                    </Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Authorization model">
        <div className="grid-2">
          <div className="stack">
            <p className="inline-note">
              The gateway authorizes every call, including tools that are hidden from the
              assistant&apos;s tool list. A hidden tool is a discovery convenience, not a
              permission.
            </p>
            <Badge tone="info">
              <CheckCircle2 aria-hidden="true" /> Deny rules always win
            </Badge>
          </div>
          <div className="stack">
            <p className="inline-note">
              Tool permissions are granted per role as
              <code> tools:&lt;server&gt;:&lt;tool&gt;</code>, with <code>*</code> wildcards
              supported.
            </p>
            <Badge tone="neutral">
              <Lock aria-hidden="true" /> Denied calls are audited
            </Badge>
          </div>
        </div>
      </Panel>
    </div>
  );
}
