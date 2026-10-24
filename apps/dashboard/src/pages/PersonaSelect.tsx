import { ArrowRight, ClipboardList, Crown, Eye, RefreshCw, ShieldAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { BrandMark } from "../components/BrandMark";
import { Badge, Button, ErrorNotice } from "../components/ui";
import type { DemoPersona } from "../types";

const ICONS: Record<string, LucideIcon> = {
  admin: Crown,
  operator: ClipboardList,
  viewer: Eye,
};

const ACCENTS: Record<string, string> = {
  admin: "is-admin",
  operator: "is-operator",
  viewer: "is-viewer",
};

interface PersonaSelectProps {
  personas: DemoPersona[];
  onSelect: (persona: DemoPersona) => void;
  busy: string | null;
  error: string | null;
  deployment: string;
  current?: string;
  onCancel?: () => void;
  onRefreshConfig?: () => void;
}

export default function PersonaSelect({
  personas,
  onSelect,
  busy,
  error,
  deployment,
  current,
  onCancel,
  onRefreshConfig,
}: PersonaSelectProps) {
  return (
    <div className="login-screen persona-screen">
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

          <h1 className="login-headline" style={{ marginTop: "var(--space-12)" }}>
            Choose a persona.
          </h1>
          <p className="login-copy" style={{ marginTop: "var(--space-4)" }}>
            Walk through the gateway as an administrator, an operator or a viewer.
            Every choice signs you in with a real session and a real gateway role —
            the server still authorizes every request.
          </p>
        </div>

        <div className="persona-aside-footer">
          <div className="demo-flag demo-flag-lg">
            <ShieldAlert aria-hidden="true" />
            ASSESSMENT DEMO
          </div>
          <p className="login-copy" style={{ fontSize: "var(--text-sm)" }}>
            Demo mode is enabled for this assessment deployment ({deployment}). It is
            not production authentication: anyone who can reach this dashboard can
            switch personas.
          </p>
        </div>
      </section>

      <main className="login-main">
        <div className="persona-panel">
          <header className="persona-header">
            <div>
              <h2 className="login-title">Enter the demo</h2>
              <p className="login-subtitle">
                No email or password needed. Switching personas replaces the current
                session.
              </p>
            </div>
            <div className="persona-header-actions">
              {onRefreshConfig && (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<RefreshCw aria-hidden="true" />}
                  onClick={onRefreshConfig}
                  disabled={busy !== null}
                >
                  Reload
                </Button>
              )}
              {onCancel && (
                <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy !== null}>
                  Back
                </Button>
              )}
            </div>
          </header>

          {error && <ErrorNotice message={error} />}

          <div className="persona-grid">
            {personas.map((persona) => {
              const Icon = ICONS[persona.id] ?? Eye;
              const isBusy = busy === persona.id;
              return (
                <article
                  key={persona.id}
                  className={`persona-card ${ACCENTS[persona.id] ?? ""}`}
                >
                  <div className="persona-card-head">
                    <span className="persona-icon">
                      <Icon aria-hidden="true" />
                    </span>
                    <div>
                      <h3 className="persona-title">{persona.title}</h3>
                      <p className="persona-summary">{persona.summary}</p>
                    </div>
                  </div>
                  <ul className="persona-capabilities">
                    {persona.capabilities.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                  <div className="persona-card-actions">
                    <Badge tone="neutral" className="persona-role">
                      role: {persona.role}
                    </Badge>
                    <Button
                      variant="primary"
                      size="sm"
                      icon={isBusy ? <RefreshCw className="spin" aria-hidden="true" /> : <ArrowRight aria-hidden="true" />}
                      onClick={() => onSelect(persona)}
                      disabled={busy !== null}
                    >
                      {isBusy ? "Entering…" : current === persona.id ? "Continue" : `Enter as ${persona.title}`}
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}
