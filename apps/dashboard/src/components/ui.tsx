import * as React from "react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Info, X } from "lucide-react";

import type { Tone } from "../lib/format";

/* -- Button ---------------------------------------------------------------- */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-soft";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "md" | "sm";
  icon?: ReactNode;
  iconOnly?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  iconOnly = false,
  className = "",
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    `btn-${variant}`,
    size === "sm" ? "btn-sm" : "",
    iconOnly ? "btn-icon" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type={type} className={classes} {...rest}>
      {icon}
      {!iconOnly && children}
    </button>
  );
}

/* -- Badge ----------------------------------------------------------------- */

interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  pulse?: boolean;
  className?: string;
}

export function Badge({ tone = "neutral", children, dot = false, pulse = false, className = "" }: BadgeProps) {
  const classes = ["badge", `badge-${tone}`, pulse ? "badge-pulse" : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes}>
      {dot && <span className="badge-dot" />}
      {children}
    </span>
  );
}

/* -- Panel ----------------------------------------------------------------- */

export function Panel({
  title,
  description,
  actions,
  children,
  flush = false,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <header className="panel-header">
          <div>
            {title && <h2 className="panel-title">{title}</h2>}
            {description && <p className="panel-description">{description}</p>}
          </div>
          {actions && <div className="row-actions">{actions}</div>}
        </header>
      )}
      <div className={flush ? "panel-body flush" : "panel-body"}>{children}</div>
    </section>
  );
}

/* -- Field ----------------------------------------------------------------- */

interface FieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
}

export function Field({ label, hint, error, children, htmlFor, className = "" }: FieldProps) {
  return (
    <div className={`field ${className}`}>
      <label className="field-label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? (
        <span className="field-error">{error}</span>
      ) : hint ? (
        <span className="field-hint">{hint}</span>
      ) : null}
    </div>
  );
}

/* -- States ---------------------------------------------------------------- */

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state-block">
      {icon && <div className="state-icon">{icon}</div>}
      <p className="state-title">{title}</p>
      {description && <p className="state-text">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorNotice({
  message,
  onRetry,
  tone = "error",
}: {
  message: string;
  onRetry?: () => void;
  tone?: "error" | "info" | "warn";
}) {
  const Icon = tone === "info" ? Info : tone === "warn" ? AlertTriangle : AlertTriangle;
  return (
    <div className={`notice ${tone === "error" ? "" : `is-${tone}`}`} role="alert">
      <Icon aria-hidden="true" />
      <div className="notice-body">{message}</div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state-block" role="status" aria-live="polite">
      <div className="state-icon">
        <span className="spinner" aria-hidden="true" />
      </div>
      <p className="state-text">{label}</p>
    </div>
  );
}

export function SkeletonRows({ rows = 4, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div style={{ padding: "var(--space-4)", display: "grid", gap: "var(--space-3)" }}>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} style={{ display: "grid", gap: "var(--space-3)", gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
          {Array.from({ length: columns }).map((__, columnIndex) => (
            <div
              key={columnIndex}
              className="skeleton"
              style={{ height: 16, opacity: 1 - rowIndex * 0.12 }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/* -- Modal ----------------------------------------------------------------- */

export function Modal({
  title,
  children,
  actions,
  onClose,
}: {
  title: string;
  children?: ReactNode;
  actions: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={ref}
      >
        <h2 className="modal-title">{title}</h2>
        {children && <div className="modal-text">{children}</div>}
        <div className="modal-actions">{actions}</div>
      </div>
    </div>
  );
}

/* -- Misc ------------------------------------------------------------------ */

export function Spinner({ label }: { label?: string }) {
  return (
    <>
      <span className="spinner" aria-hidden="true" />
      {label ? <span className="visually-hidden">{label}</span> : null}
    </>
  );
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant="secondary"
      icon={copied ? <Check aria-hidden="true" /> : null}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? "Copied" : label}
    </Button>
  );
}

export function CloseButton({ onClick, label = "Close" }: { onClick: () => void; label?: string }) {
  return (
    <button type="button" className="icon-button" onClick={onClick} aria-label={label}>
      <X aria-hidden="true" />
    </button>
  );
}
