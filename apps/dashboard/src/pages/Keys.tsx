import { useCallback, useEffect, useState } from "react";
import { KeyRound, Plus, ShieldAlert, Trash2 } from "lucide-react";

import { api, ApiError } from "../api";
import type { ApiKey } from "../types";
import {
  Badge,
  Button,
  CopyButton,
  EmptyState,
  ErrorNotice,
  Field,
  Modal,
  Panel,
  SkeletonRows,
} from "../components/ui";
import { formatDate, formatRelative } from "../lib/format";

const MASK = "•".repeat(12);

export default function Keys({ canCreate }: { canCreate: boolean }) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState<ApiKey | null>(null);

  const load = useCallback(async () => {
    try {
      setKeys(await api.keys());
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

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setCreating(true);
    try {
      const created = await api.createKey(name.trim() || "default");
      setSecret(created.api_key);
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: number) {
    try {
      await api.deleteKey(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const activeCount = keys.filter((key) => key.active).length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2 className="page-title">API keys</h2>
          <p className="page-description">
            Keys authenticate MCP clients at <code>/mcp</code> using{" "}
            <code>Authorization: Bearer …</code>. The plaintext is shown once, at creation.
          </p>
        </div>
        <div className="page-actions">
          <Badge tone="neutral">
            <KeyRound aria-hidden="true" /> {activeCount} active / {keys.length} total
          </Badge>
        </div>
      </header>

      {error && <ErrorNotice message={error} onRetry={() => void load()} />}

      {secret && (
        <div className="secret-reveal">
          <div className="row-between">
            <p className="row-between" style={{ gap: "var(--space-2)" }}>
              <ShieldAlert aria-hidden="true" size={16} />
              <strong>Copy this key now — it is never shown again.</strong>
            </p>
            <Button size="sm" variant="ghost" onClick={() => setSecret(null)}>
              Dismiss
            </Button>
          </div>
          <div className="secret-value">
            <code>{secret}</code>
            <CopyButton value={secret} label="Copy key" />
          </div>
        </div>
      )}

      <Panel
        title="Issue a new key"
        description="Keys inherit the permissions of the account they belong to."
      >
        {canCreate ? (
          <form onSubmit={create}>
            <div className="form-row">
              <Field
                label="Key name"
                htmlFor="key-name"
                hint="For example: “CI pipeline” or “Claude Desktop”."
              >
                <input
                  id="key-name"
                  className="input"
                  placeholder="CI pipeline"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={120}
                />
              </Field>
              <Button type="submit" variant="primary" icon={<Plus aria-hidden="true" />} disabled={creating}>
                {creating ? "Creating…" : "Create key"}
              </Button>
            </div>
          </form>
        ) : (
          <EmptyState
            icon={<ShieldAlert aria-hidden="true" />}
            title="Key management is disabled for this account"
            description="You can review the keys issued to you, but only an administrator can issue or revoke them."
          />
        )}
      </Panel>

      <Panel title="Issued keys" flush>
        {loading ? (
          <SkeletonRows rows={3} columns={4} />
        ) : keys.length === 0 ? (
          <EmptyState
            icon={<KeyRound aria-hidden="true" />}
            title="No API keys yet"
            description="Create one above to let an MCP client call the gateway directly."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Key</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Last used</th>
                  <th>Expires</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id}>
                    <td className="cell-primary">{key.name}</td>
                    <td className="mono" title="Only the prefix is stored in readable form">
                      {key.prefix}
                      {MASK}
                    </td>
                    <td>
                      <Badge tone={key.active ? "ok" : "neutral"} dot>
                        {key.active ? "Active" : "Revoked"}
                      </Badge>
                    </td>
                    <td className="text-muted">{formatDate(key.created_at)}</td>
                    <td className="text-muted">
                      {key.last_used_at ? formatRelative(key.last_used_at) : "never"}
                    </td>
                    <td className="text-muted">
                      {key.expires_at ? formatDate(key.expires_at) : "never"}
                    </td>
                    <td>
                      <div className="row-actions">
                        {key.active && (
                          <Button
                            size="sm"
                            variant="danger-soft"
                            icon={<Trash2 aria-hidden="true" />}
                            onClick={() => setPendingRevoke(key)}
                          >
                            Revoke
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {pendingRevoke && (
        <Modal
          title="Revoke API key?"
          onClose={() => setPendingRevoke(null)}
          actions={
            <>
              <Button variant="ghost" onClick={() => setPendingRevoke(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  const key = pendingRevoke;
                  setPendingRevoke(null);
                  void revoke(key.id);
                }}
              >
                Revoke key
              </Button>
            </>
          }
        >
          <strong>{pendingRevoke.name}</strong> will stop authenticating immediately. Clients using
          it will receive <code>401 Unauthorized</code>. This cannot be undone.
        </Modal>
      )}
    </div>
  );
}
