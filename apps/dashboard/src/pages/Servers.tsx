import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CircleSlash,
  Link2,
  Plus,
  Power,
  RefreshCw,
  Server as ServerIcon,
  Trash2,
  Wrench,
} from "lucide-react";

import { api, ApiError } from "../api";
import type { Server } from "../types";
import {
  Badge,
  Button,
  EmptyState,
  ErrorNotice,
  Field,
  Modal,
  Panel,
  SkeletonRows,
} from "../components/ui";
import { formatRelative, humanize, serverTone } from "../lib/format";

export default function Servers({ canManage }: { canManage: boolean }) {
  const [servers, setServers] = useState<Server[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<Server | null>(null);
  const [form, setForm] = useState({
    server_id: "",
    name: "",
    url: "",
    description: "",
    credential_type: "none",
    credential: "",
  });

  const load = useCallback(async () => {
    try {
      setServers(await api.servers());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(server: Server, action: () => Promise<unknown>) {
    setError(null);
    setBusyId(server.server_id);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function register(event: React.FormEvent) {
    event.preventDefault();
    const payload: Record<string, unknown> = {
      server_id: form.server_id.trim(),
      name: form.name.trim(),
      url: form.url.trim(),
      description: form.description.trim() || undefined,
      credential_type: form.credential_type,
    };
    if (form.credential_type !== "none" && form.credential) {
      payload.credential = form.credential;
    }
    setError(null);
    try {
      await api.createServer(payload as never);
      setForm({
        server_id: "",
        name: "",
        url: "",
        description: "",
        credential_type: "none",
        credential: "",
      });
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2 className="page-title">MCP servers</h2>
          <p className="page-description">
            Upstream Model Context Protocol servers aggregated by the gateway. A server is only
            reported healthy when its tools were discovered successfully.
          </p>
        </div>
        {canManage && (
          <div className="page-actions">
            <Button
              variant="primary"
              icon={<Plus aria-hidden="true" />}
              onClick={() => setShowForm((value) => !value)}
            >
              Register server
            </Button>
          </div>
        )}
      </header>

      {error && <ErrorNotice message={error} onRetry={() => void load()} />}

      {canManage && showForm && (
        <Panel
          title="Register an upstream server"
          description="Credentials are stored server-side, encrypted, and never returned by the API."
        >
          <form onSubmit={register}>
            <div className="form-row">
              <Field label="Server id" htmlFor="server-id" hint="Lowercase identifier used as the tool prefix.">
                <input
                  id="server-id"
                  className="input"
                  placeholder="inventory"
                  value={form.server_id}
                  onChange={(event) => setForm({ ...form, server_id: event.target.value })}
                  required
                />
              </Field>
              <Field label="Display name" htmlFor="server-name">
                <input
                  id="server-name"
                  className="input"
                  placeholder="Inventory MCP"
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  required
                />
              </Field>
              <Field label="Endpoint" htmlFor="server-url">
                <input
                  id="server-url"
                  className="input"
                  placeholder="http://inventory-mcp:8102/mcp"
                  value={form.url}
                  onChange={(event) => setForm({ ...form, url: event.target.value })}
                  required
                />
              </Field>
            </div>
            <div className="form-row" style={{ marginTop: "var(--space-4)" }}>
              <Field label="Purpose" htmlFor="server-description" className="field-wide">
                <input
                  id="server-description"
                  className="input"
                  placeholder="Stock lookup and low-stock detection"
                  value={form.description}
                  onChange={(event) => setForm({ ...form, description: event.target.value })}
                />
              </Field>
              <Field label="Credential" htmlFor="server-credential">
                <select
                  id="server-credential"
                  className="select"
                  value={form.credential_type}
                  onChange={(event) => setForm({ ...form, credential_type: event.target.value })}
                >
                  <option value="none">No credential</option>
                  <option value="bearer">Bearer token</option>
                  <option value="header">Custom header</option>
                </select>
              </Field>
              {form.credential_type !== "none" && (
                <Field label="Secret" htmlFor="server-secret" hint="Never shown again.">
                  <input
                    id="server-secret"
                    className="input"
                    type="password"
                    autoComplete="off"
                    value={form.credential}
                    onChange={(event) => setForm({ ...form, credential: event.target.value })}
                  />
                </Field>
              )}
            </div>
            <div className="row-actions" style={{ marginTop: "var(--space-5)", justifyContent: "flex-start" }}>
              <Button type="submit" variant="primary">
                Register server
              </Button>
              <Button variant="ghost" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Panel>
      )}

      {loading ? (
        <div className="panel">
          <SkeletonRows rows={3} columns={4} />
        </div>
      ) : servers.length === 0 ? (
        <Panel flush>
          <EmptyState
            icon={<ServerIcon aria-hidden="true" />}
            title="No MCP servers registered"
            description={
              canManage
                ? "Register an upstream server to expose its tools through the gateway."
                : "An administrator has not registered any upstream servers yet."
            }
          />
        </Panel>
      ) : (
        <div className="server-grid">
          {servers.map((server) => {
            const tone = serverTone(server.status);
            const busy = busyId === server.server_id;
            return (
              <article
                key={server.server_id}
                className={`server-card ${
                  server.status === "unhealthy"
                    ? "is-unhealthy"
                    : server.status === "disabled"
                      ? "is-disabled"
                      : ""
                }`}
              >
                <div className="server-card-head">
                  <div>
                    <h3 className="server-name">{server.name}</h3>
                    <p className="server-id">{server.server_id}</p>
                  </div>
                  <Badge tone={tone} dot pulse={server.status === "healthy"}>
                    {server.status === "healthy" ? "Healthy" : humanize(server.status)}
                  </Badge>
                </div>

                {server.description && <p className="server-description">{server.description}</p>}

                <div className="server-meta">
                  <div className="server-meta-item">
                    <span className="server-meta-label">Tools</span>
                    <span className="server-meta-value">{server.tool_count}</span>
                  </div>
                  <div className="server-meta-item">
                    <span className="server-meta-label">Transport</span>
                    <span className="server-meta-value">{server.transport}</span>
                  </div>
                  <div className="server-meta-item">
                    <span className="server-meta-label">Credential</span>
                    <span className="server-meta-value">
                      {server.has_credential ? server.credential_type : "none"}
                    </span>
                  </div>
                  <div className="server-meta-item">
                    <span className="server-meta-label">Last checked</span>
                    <span className="server-meta-value">
                      {formatRelative(server.last_checked_at)}
                    </span>
                  </div>
                </div>

                <div className="server-meta-item">
                  <span className="server-meta-label">Endpoint</span>
                  <span className="server-meta-value mono" title={server.url ?? ""}>
                    {server.url ?? "—"}
                  </span>
                </div>

                {server.last_error && (
                  <p className="server-error">
                    <AlertTriangle aria-hidden="true" />
                    <span>{server.last_error}</span>
                  </p>
                )}

                {server.status === "disabled" && (
                  <p className="server-error" style={{ color: "var(--text-secondary)", background: "var(--surface-sunken)", borderColor: "var(--border)" }}>
                    <CircleSlash aria-hidden="true" />
                    <span>Disabled — its tools are not aggregated.</span>
                  </p>
                )}

                {canManage && (
                  <div className="server-actions">
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Power aria-hidden="true" />}
                      disabled={busy}
                      onClick={() =>
                        void run(server, () =>
                          api.setServerEnabled(server.server_id, !server.enabled),
                        )
                      }
                    >
                      {server.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<RefreshCw aria-hidden="true" />}
                      disabled={busy}
                      onClick={() => void run(server, () => api.refreshServer(server.server_id))}
                    >
                      Refresh
                    </Button>
                    <Button
                      size="sm"
                      variant="danger-soft"
                      icon={<Trash2 aria-hidden="true" />}
                      disabled={busy}
                      onClick={() => setPendingRemoval(server)}
                    >
                      Remove
                    </Button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      <Panel title="How tools are named" description="The gateway namespaces every upstream tool.">
        <p className="inline-note">
          A tool exposed as <code>list_products</code> by the server <code>woocommerce</code> is
          published as <code>woocommerce__list_products</code>. The upstream name is preserved
          verbatim, including its schema and description.
        </p>
        <div className="row-actions" style={{ marginTop: "var(--space-4)", justifyContent: "flex-start" }}>
          <Badge tone="neutral">
            <Link2 aria-hidden="true" /> {servers.length} registered
          </Badge>
          <Badge tone="neutral">
            <Wrench aria-hidden="true" />{" "}
            {servers.reduce((total, server) => total + server.tool_count, 0)} tools
          </Badge>
        </div>
      </Panel>

      {pendingRemoval && (
        <Modal
          title="Remove MCP server?"
          onClose={() => setPendingRemoval(null)}
          actions={
            <>
              <Button variant="ghost" onClick={() => setPendingRemoval(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  const server = pendingRemoval;
                  setPendingRemoval(null);
                  void run(server, () => api.deleteServer(server.server_id));
                }}
              >
                Remove server
              </Button>
            </>
          }
        >
          <code>{pendingRemoval.server_id}</code> will be removed from the registry and its tools
          will no longer be aggregated. Existing audit records are kept.
        </Modal>
      )}
    </div>
  );
}
