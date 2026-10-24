import { useState } from "react";
import { ArrowRight, Leaf, Lock, Mail } from "lucide-react";

import { api, ApiError } from "../api";
import type { User } from "../types";
import { BrandMark } from "../components/BrandMark";
import { Button, ErrorNotice } from "../components/ui";

export default function Login({ onLoggedIn }: { onLoggedIn: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await api.login(email.trim(), password);
      onLoggedIn(result.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <section className="login-aside">
        <div>
          <div className="row-between" style={{ justifyContent: "flex-start", gap: "var(--space-3)" }}>
            <span className="brand-tile" style={{ width: 38, height: 38 }}>
              <BrandMark size={22} />
            </span>
            <div>
              <p
                style={{
                  fontFamily: "var(--font-display)",
                  fontSize: "var(--text-lg)",
                  fontWeight: 600,
                  color: "#ffffff",
                  lineHeight: 1.1,
                }}
              >
                Urumi
              </p>
              <p
                style={{
                  fontSize: "var(--text-2xs)",
                  letterSpacing: "var(--tracking-wider)",
                  textTransform: "uppercase",
                  color: "var(--sidebar-muted)",
                }}
              >
                MCP Gateway
              </p>
            </div>
          </div>
        </div>

        <div>
          <h1 className="login-headline">One gateway for every operational tool.</h1>
          <p className="login-copy">
            Urumi aggregates WooCommerce, inventory and shipping MCP servers behind a single
            authenticated endpoint — with role-based permissions and an audit trail on every call.
          </p>
        </div>

        <ul className="login-points">
          <li className="login-point">
            <Leaf aria-hidden="true" />
            <span>Live WooCommerce catalog, stock and order data</span>
          </li>
          <li className="login-point">
            <Lock aria-hidden="true" />
            <span>Per-role tool permissions, enforced on every call</span>
          </li>
          <li className="login-point">
            <ArrowRight aria-hidden="true" />
            <span>Audit trail for success, denial and failure</span>
          </li>
        </ul>
      </section>

      <section className="login-main">
        <div className="login-card">
          <div>
            <p
              style={{
                fontSize: "var(--text-xs)",
                fontWeight: 600,
                letterSpacing: "var(--tracking-wider)",
                textTransform: "uppercase",
                color: "var(--urumi-emerald)",
              }}
            >
              Sign in
            </p>
            <h2 className="login-title">Welcome back</h2>
            <p className="login-subtitle">Use your team account to open the gateway.</p>
          </div>

          {error && <ErrorNotice message={error} />}

          <form onSubmit={submit}>
            <div className="field">
              <label className="field-label" htmlFor="login-email">
                Email
              </label>
              <div className="input-with-icon">
                <Mail aria-hidden="true" />
                <input
                  id="login-email"
                  className="input"
                  type="email"
                  autoComplete="username"
                  placeholder="you@urumi.dev"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </div>
            </div>

            <div className="field" style={{ marginTop: "var(--space-4)" }}>
              <label className="field-label" htmlFor="login-password">
                Password
              </label>
              <div className="input-with-icon">
                <Lock aria-hidden="true" />
                <input
                  id="login-password"
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </div>
            </div>

            <Button
              type="submit"
              variant="primary"
              className="block"
              disabled={busy}
              style={{ marginTop: "var(--space-5)" }}
            >
              {busy ? "Signing in…" : "Sign in"}
              {!busy && <ArrowRight aria-hidden="true" />}
            </Button>
          </form>

          <p className="inline-note">
            Sessions use an HTTP-only cookie with SameSite=strict, plus CSRF protection on every
            state-changing request.
          </p>
        </div>
      </section>
    </div>
  );
}
