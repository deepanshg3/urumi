import { useCallback, useEffect, useState } from "react";
import { KeyRound, UserPlus, Users as UsersIcon } from "lucide-react";

import { api, ApiError } from "../api";
import type { User } from "../types";
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
import { formatDate } from "../lib/format";
import { ROLE_DESCRIPTIONS, roleLabel } from "../lib/permissions";

const ROLES = ["admin", "member", "viewer"];

export default function Users({ canManageUsers }: { canManageUsers: boolean }) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [pendingEdit, setPendingEdit] = useState<User | null>(null);
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [form, setForm] = useState({
    email: "",
    password: "",
    display_name: "",
    roles: ["member"] as string[],
  });

  const load = useCallback(async () => {
    try {
      setUsers(await api.users());
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
      await api.createUser({
        email: form.email.trim(),
        password: form.password,
        display_name: form.display_name.trim() || undefined,
        roles: form.roles.length ? form.roles : ["member"],
      });
      setForm({ email: "", password: "", display_name: "", roles: ["member"] });
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  async function toggleActive(user: User) {
    setError(null);
    try {
      await api.updateUser(user.id, { is_active: !user.is_active });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function submitPassword(event?: React.FormEvent) {
    event?.preventDefault();
    if (!passwordTarget) return;
    setError(null);
    setSavingPassword(true);
    try {
      await api.setUserPassword(passwordTarget.id, newPassword);
      setPasswordTarget(null);
      setNewPassword("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSavingPassword(false);
    }
  }

  if (!canManageUsers) {
    return (
      <div className="page">
        <header className="page-header">
          <div>
            <h2 className="page-title">Team</h2>
            <p className="page-description">
              Only administrators can view the user directory.
            </p>
          </div>
        </header>
        <Panel flush>
          <EmptyState
            icon={<UsersIcon aria-hidden="true" />}
            title="Administrators only"
            description="Ask an administrator to manage accounts and role assignments."
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2 className="page-title">Team</h2>
          <p className="page-description">
            Accounts and their gateway roles. Roles decide which tools each person may call.
          </p>
        </div>
        <div className="page-actions">
          <Button
            variant="primary"
            icon={<UserPlus aria-hidden="true" />}
            onClick={() => setShowForm((value) => !value)}
          >
            Add member
          </Button>
        </div>
      </header>

      {error && <ErrorNotice message={error} onRetry={() => void load()} />}

      {showForm && (
        <Panel title="Add a team member" description="They sign in with email and password.">
          <form onSubmit={create}>
            <div className="form-row">
              <Field label="Email" htmlFor="user-email">
                <input
                  id="user-email"
                  className="input"
                  type="email"
                  placeholder="teammate@urumi.dev"
                  value={form.email}
                  onChange={(event) => setForm({ ...form, email: event.target.value })}
                  required
                />
              </Field>
              <Field label="Display name" htmlFor="user-name">
                <input
                  id="user-name"
                  className="input"
                  placeholder="Ava Chen"
                  value={form.display_name}
                  onChange={(event) => setForm({ ...form, display_name: event.target.value })}
                />
              </Field>
              <Field label="Temporary password" htmlFor="user-password">
                <input
                  id="user-password"
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={form.password}
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                  required
                  minLength={8}
                />
              </Field>
            </div>
            <fieldset className="role-picker">
              <legend className="field-label">Roles</legend>
              {ROLES.map((role) => (
                <label className="checkbox" key={role}>
                  <input
                    type="checkbox"
                    checked={form.roles.includes(role)}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        roles: event.target.checked
                          ? [...form.roles, role]
                          : form.roles.filter((value) => value !== role),
                      })
                    }
                  />
                  <span>
                    <strong>{roleLabel(role)}</strong>
                    <span className="text-muted">
                      {" "}
                      — {ROLE_DESCRIPTIONS[role] ?? "custom permissions"}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
            <div className="row-actions" style={{ marginTop: "var(--space-5)", justifyContent: "flex-start" }}>
              <Button type="submit" variant="primary" disabled={creating}>
                {creating ? "Creating…" : "Create member"}
              </Button>
              <Button variant="ghost" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Panel>
      )}

      <Panel title={`${users.length} account${users.length === 1 ? "" : "s"}`} flush>
        {loading ? (
          <SkeletonRows rows={3} columns={4} />
        ) : users.length === 0 ? (
          <EmptyState
            icon={<UsersIcon aria-hidden="true" />}
            title="No accounts yet"
            description="Add the first team member to grant them access."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Roles</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td className="cell-primary">{user.display_name || "—"}</td>
                    <td className="text-muted">{user.email}</td>
                    <td>
                      <div className="row-actions" style={{ gap: "var(--space-1)" }}>
                        {user.roles.map((role) => (
                          <Badge key={role} tone={role === "admin" ? "info" : "neutral"}>
                            {roleLabel(role)}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td>
                      <Badge tone={user.is_active ? "ok" : "warn"} dot>
                        {user.is_active ? "Active" : "Disabled"}
                      </Badge>
                    </td>
                    <td className="text-muted">{formatDate(user.created_at)}</td>
                    <td>
                      <div className="row-actions">
                        <Button size="sm" variant="secondary" onClick={() => setPendingEdit(user)}>
                          Manage
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {pendingEdit && (
        <Modal
          title={pendingEdit.display_name || pendingEdit.email}
          onClose={() => setPendingEdit(null)}
          actions={
            <>
              <Button
                variant="secondary"
                icon={<KeyRound aria-hidden="true" />}
                onClick={() => {
                  const user = pendingEdit;
                  setPendingEdit(null);
                  setNewPassword("");
                  setPasswordTarget(user);
                }}
              >
                Set password
              </Button>
              <Button variant="ghost" onClick={() => setPendingEdit(null)}>
                Cancel
              </Button>
              <Button
                variant={pendingEdit.is_active ? "danger-soft" : "primary"}
                onClick={() => {
                  const user = pendingEdit;
                  setPendingEdit(null);
                  void toggleActive(user);
                }}
              >
                {pendingEdit.is_active ? "Disable account" : "Enable account"}
              </Button>
            </>
          }
        >
          <p>
            <strong>{pendingEdit.email}</strong>
          </p>
          <p className="text-muted">
            Roles: {pendingEdit.roles.map(roleLabel).join(", ") || "none"} · Joined{" "}
            {formatDate(pendingEdit.created_at)}
          </p>
        </Modal>
      )}

      {passwordTarget && (
        <Modal
          title={`Set a new password`}
          onClose={() => setPasswordTarget(null)}
          actions={
            <>
              <Button variant="ghost" onClick={() => setPasswordTarget(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={savingPassword || newPassword.length < 12}
                onClick={() => void submitPassword()}
              >
                {savingPassword ? "Saving…" : "Set password"}
              </Button>
            </>
          }
        >
          <form onSubmit={submitPassword}>
            <Field
              label={`New password for ${passwordTarget.email}`}
              htmlFor="reset-password"
              hint="At least 12 characters. Every browser session of this account is signed out."
            >
              <input
                id="reset-password"
                className="input"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
                minLength={12}
              />
            </Field>
          </form>
        </Modal>
      )}
    </div>
  );
}
