import type { ReactNode } from "react";

export const STATUS_STYLE: Record<string, string> = {
  DONE_CLEAN: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  DONE_WITH_FINDINGS: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  FLAGGED: "border-red-500/40 bg-red-500/15 text-red-300",
  INCOMPLETE_EVALUATION: "border-slate-500/40 bg-slate-500/20 text-slate-300",
  EVALUATOR_ERROR: "border-fuchsia-500/40 bg-fuchsia-500/15 text-fuchsia-300",
};

export const TYPE_STYLE: Record<string, string> = {
  ENGINEERING_WEAKNESS: "border-amber-500/30 bg-amber-500/15 text-amber-300",
  ANOMALY: "border-sky-500/30 bg-sky-500/15 text-sky-300",
  MATERIAL_INTEGRITY_CONCERN: "border-red-500/30 bg-red-500/15 text-red-300",
  SECURITY: "border-rose-500/30 bg-rose-500/15 text-rose-300",
};

export const SEVERITY_STYLE: Record<string, string> = {
  LOW: "border-slate-600 text-slate-300",
  MEDIUM: "border-amber-500/40 text-amber-300",
  HIGH: "border-orange-500/50 text-orange-300",
  CRITICAL: "border-red-500/60 text-red-300",
};

export const TASK_STATUS_STYLE: Record<string, string> = {
  COMPARED: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  ABSOLUTE_ONLY: "border-sky-500/40 bg-sky-500/15 text-sky-300",
  INSUFFICIENT_PEERS: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  INSUFFICIENT_DATA: "border-slate-500/40 bg-slate-500/15 text-slate-300",
  TASK_NOT_ESTABLISHED: "border-rose-500/40 bg-rose-500/15 text-rose-300",
};

export const RELATION_STYLE: Record<string, string> = {
  EXPLICIT: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  SEMANTIC: "border-violet-500/40 bg-violet-500/10 text-violet-300",
  UNCERTAIN: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  UNRELATED: "border-slate-600 bg-slate-800/40 text-slate-300",
  SAME_TASK: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  SEMANTIC_EQUIVALENT: "border-violet-500/40 bg-violet-500/10 text-violet-300",
  DUPLICATE: "border-amber-500/40 bg-amber-500/10 text-amber-300",
};

export const REQUIREMENT_STYLE: Record<string, string> = {
  COVERED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  PARTIAL: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  MISSING: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  UNVERIFIED: "border-slate-600 bg-slate-800/40 text-slate-300",
};

export const REQUIREMENT_ICON: Record<string, string> = {
  COVERED: "✓",
  PARTIAL: "◐",
  MISSING: "✕",
  UNVERIFIED: "?",
};

export const STATUS_LABEL: Record<string, string> = {
  DONE_CLEAN: "Clean",
  DONE_WITH_FINDINGS: "Findings",
  FLAGGED: "Flagged",
  INCOMPLETE_EVALUATION: "Incomplete",
  EVALUATOR_ERROR: "Evaluator error",
};

export const TASK_STATUS_LABEL: Record<string, string> = {
  COMPARED: "Peer-compared",
  ABSOLUTE_ONLY: "Absolute only",
  INSUFFICIENT_PEERS: "Insufficient peers",
  INSUFFICIENT_DATA: "Insufficient data",
  TASK_NOT_ESTABLISHED: "Not established",
};

export const inputClass =
  "w-full rounded-lg border border-slate-700/80 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-sky-400 focus:ring-2 focus:ring-sky-400/20 disabled:cursor-not-allowed disabled:opacity-50";

export const buttonPrimary =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-sky-300/50 bg-sky-400 px-4 py-2.5 text-sm font-semibold text-slate-950 shadow-[0_10px_30px_-16px_rgba(56,189,248,0.9)] transition hover:bg-sky-300 focus-visible:ring-2 focus-visible:ring-sky-200 disabled:cursor-not-allowed disabled:opacity-40";

export const buttonSecondary =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-950/70 px-3.5 py-2 text-sm font-medium text-slate-200 transition hover:border-sky-500/60 hover:bg-slate-900 focus-visible:ring-2 focus-visible:ring-sky-300/50 disabled:cursor-not-allowed disabled:opacity-40";

export const buttonGhost =
  "inline-flex items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-400 transition hover:bg-slate-800/70 hover:text-slate-100 focus-visible:ring-2 focus-visible:ring-sky-300/50 disabled:cursor-not-allowed disabled:opacity-40";

export const fmt = (value: unknown): string | number => {
  if (typeof value === "number") return value.toLocaleString("en-US");
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "n/a";
  return String(value);
};

export const pct = (value: unknown) =>
  typeof value === "number" ? `${Math.round(value * 100)}%` : "n/a";

export const scoreText = (value: unknown, digits = 1) =>
  typeof value === "number" ? `${value.toFixed(digits)}/100` : "not measurable";

export const formatTimestamp = (value: unknown) => {
  if (!value) return "time unavailable";
  return String(value)
    .replace("T", " ")
    .replace(/\.\d+(?=(?:Z|[+-]\d{2}:\d{2})$)/, "")
    .replace(/\+00:00$/, " UTC")
    .replace(/Z$/, " UTC");
};

export const statusLabel = (status: string | null | undefined) =>
  (status && STATUS_LABEL[status]) || (status ? status.replaceAll("_", " ") : "Unknown");

export const taskStatusLabel = (status: string | null | undefined) =>
  (status && TASK_STATUS_LABEL[status]) || (status ? status.replaceAll("_", " ") : "Unknown");

export function Badge({
  children,
  className = "",
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex max-w-full items-center rounded-md border px-2 py-0.5 font-mono text-[11px] leading-4 tracking-wide ${className}`}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}

export function Section({
  id,
  title,
  hint,
  action,
  children,
  className = "",
}: {
  id?: string;
  title: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      id={id}
      className={`scroll-mt-24 rounded-xl border border-slate-800/90 bg-slate-900/55 p-4 shadow-[0_20px_70px_-52px_rgba(56,189,248,0.55)] sm:p-5 ${className}`}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span aria-hidden="true" className="mt-0.5 h-4 w-1 shrink-0 rounded-full bg-sky-400/80" />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-100">{title}</h2>
            {hint && <p className="mt-1 text-xs leading-relaxed text-slate-500">{hint}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  tone = "",
  hint,
}: {
  label: string;
  value: ReactNode;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-950/55 px-3.5 py-3 transition hover:border-slate-700">
      <div className="text-[10px] uppercase tracking-[0.15em] text-slate-500">{label}</div>
      <div className={`mt-1 break-words font-mono text-xl leading-tight ${tone || "text-slate-100"}`}>{value}</div>
      {hint && <div className="mt-1 text-[11px] leading-snug text-slate-500">{hint}</div>}
    </div>
  );
}

export function KV({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-800/70 py-1.5 text-sm last:border-0">
      <span className="shrink-0 text-slate-500">{k}</span>
      <span className="min-w-0 break-words text-right font-mono text-slate-200">{v}</span>
    </div>
  );
}

export function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-28 shrink-0 text-slate-400">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded bg-slate-800">
        <div
          className="h-2 rounded bg-sky-400/80"
          style={{ width: `${max ? Math.max(1, (value / max) * 100) : 0}%` }}
        />
      </div>
      <span className="w-16 shrink-0 text-right font-mono text-slate-200">{fmt(value)}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-700/80 bg-slate-950/35 px-5 py-10 text-center"
    >
      <span
        aria-hidden="true"
        className="mb-3 grid h-10 w-10 place-items-center rounded-full border border-slate-700 bg-slate-900 text-slate-400"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
          <circle cx="11" cy="11" r="6" />
          <path d="m16 16 4 4" />
        </svg>
      </span>
      <p className="text-sm font-medium text-slate-200">{title}</p>
      <p className="mt-1 max-w-md text-xs leading-relaxed text-slate-500">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2 py-2">
      {[0, 1, 2].map((index) => (
        <div
          key={index}
          className="loading-shimmer relative h-9 overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50"
          style={{ opacity: 1 - index * 0.2 }}
        />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ScoreRing({
  value,
  label = "Final task score",
}: {
  value: number | null | undefined;
  label?: string;
}) {
  const score = typeof value === "number" ? Math.max(0, Math.min(100, value)) : null;
  const color =
    score === null
      ? "#334155"
      : score >= 80
        ? "#34d399"
        : score >= 60
          ? "#38bdf8"
          : score >= 40
            ? "#fbbf24"
            : "#fb7185";
  return (
    <div className="flex items-center gap-4">
      <div
        role="img"
        aria-label={`${label}: ${score === null ? "not measurable" : `${score.toFixed(1)} out of 100`}`}
        className="relative grid h-24 w-24 shrink-0 place-items-center rounded-full p-[7px]"
        style={{
          background:
            score === null
              ? "conic-gradient(#1e293b 0deg 360deg)"
              : `conic-gradient(${color} ${score * 3.6}deg, #1e293b ${score * 3.6}deg 360deg)`,
        }}
      >
        <div className="grid h-full w-full place-items-center rounded-full border border-slate-800 bg-slate-950 text-center">
          <div>
            <div className="font-mono text-xl font-semibold leading-none text-slate-50">
              {score === null ? "—" : score.toFixed(1)}
            </div>
            <div className="mt-1 text-[9px] uppercase tracking-[0.16em] text-slate-400">/ 100</div>
          </div>
        </div>
      </div>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
        <div className="mt-1 text-sm text-slate-300">
          {score === null ? "Not measurable from static evidence." : score >= 80 ? "Strong task evidence" : score >= 60 ? "Moderate task evidence" : score >= 40 ? "Partial task evidence" : "Limited task evidence"}
        </div>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          Absolute evidence remains the primary term. Peer context is a small, separate contribution.
        </p>
      </div>
    </div>
  );
}

export function ScoreBar({
  label,
  value,
  detail,
}: {
  label: string;
  value: number | null | undefined;
  detail?: string;
}) {
  const score = typeof value === "number" ? Math.max(0, Math.min(100, value)) : null;
  const color =
    score === null
      ? "bg-slate-700"
      : score >= 80
        ? "bg-emerald-400"
        : score >= 60
          ? "bg-sky-400"
          : score >= 40
            ? "bg-amber-400"
            : "bg-rose-400";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono text-slate-200">{score === null ? "not measurable" : score.toFixed(1)}</span>
      </div>
      <div
        className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score === null ? undefined : score}
        aria-valuetext={score === null ? "not measurable" : `${score.toFixed(1)} out of 100`}
      >
        <div className={`h-full rounded-full transition-[width] duration-500 ${color}`} style={{ width: `${score ?? 0}%` }} />
      </div>
      {detail && <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">{detail}</p>}
    </div>
  );
}

export function FilterChip({
  children,
  onRemove,
  label,
}: {
  children: ReactNode;
  onRemove: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onRemove}
      aria-label={`Remove filter: ${label}`}
      className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[11px] text-sky-200 transition hover:border-sky-400/60 hover:bg-sky-500/15"
    >
      <span className="truncate">{children}</span>
      <span aria-hidden="true" className="text-sky-400">×</span>
    </button>
  );
}
