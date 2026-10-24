/** Small formatting helpers shared by the dashboard pages. */

const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const TIME_ONLY = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const DATE_ONLY = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
});

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return DATE_TIME.format(date);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return DATE_ONLY.format(date);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return TIME_ONLY.format(date);
}

/** "3 minutes ago" style timestamp; falls back to an absolute date when old. */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const deltaMs = date.getTime() - Date.now();
  const abs = Math.abs(deltaMs);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 1000],
    ["minute", 60_000],
    ["hour", 3_600_000],
    ["day", 86_400_000],
    ["week", 604_800_000],
    ["month", 2_629_800_000],
    ["year", 31_557_600_000],
  ];
  if (abs < 45_000) return "just now";
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  let chosen = units[0];
  for (const unit of units) {
    if (abs >= unit[1]) chosen = unit;
  }
  return formatter.format(Math.round(deltaMs / chosen[1]), chosen[0]);
}

export function formatLatency(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1) return "<1 ms";
  return `${Math.round(value)} ms`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat().format(value);
}

export function initials(name: string | null | undefined, fallback: string): string {
  const source = (name ?? "").trim();
  if (!source) return fallback.slice(0, 2).toUpperCase();
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  if (parts.length === 0) return fallback.slice(0, 2).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

export type Tone = "ok" | "warn" | "error" | "info" | "neutral";

/** Map a gateway server status to a visual tone. */
export function serverTone(status: string): Tone {
  switch (status) {
    case "healthy":
      return "ok";
    case "unhealthy":
      return "error";
    case "disabled":
      return "neutral";
    default:
      return "warn";
  }
}

/** Map an audit / tool-call status to a visual tone. */
export function outcomeTone(status: string): Tone {
  switch (status) {
    case "success":
    case "ok":
      return "ok";
    case "denied":
    case "forbidden":
      return "warn";
    case "error":
    case "failed":
      return "error";
    case "timeout":
      return "warn";
    default:
      return "neutral";
  }
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const cleaned = value.replace(/[_-]+/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}
