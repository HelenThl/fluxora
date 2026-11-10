// Small shared pieces. Colour is never the only signal: every badge also carries a word.
import type { ReactNode } from "react";

const tones = {
  good: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  bad: "bg-red-50 text-red-700 ring-red-600/20",
  warn: "bg-amber-50 text-amber-800 ring-amber-600/25",
  info: "bg-indigo-50 text-indigo-700 ring-indigo-600/20",
  muted: "bg-zinc-50 text-zinc-600 ring-zinc-500/20",
} as const;
export type Tone = keyof typeof tones;

const dots: Record<Tone, string> = {
  good: "bg-emerald-500",
  bad: "bg-red-500",
  warn: "bg-amber-500",
  info: "bg-indigo-500",
  muted: "bg-zinc-400",
};

const values: Record<Tone, string> = {
  good: "text-emerald-700",
  bad: "text-red-700",
  warn: "text-amber-700",
  info: "text-zinc-900",
  muted: "text-zinc-900",
};

export function Dot({ tone }: { tone: Tone }) {
  return <span aria-hidden="true" className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${dots[tone]}`} />;
}

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-px text-2xs font-medium ring-1 ring-inset ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function verdictTone(status: string): Tone {
  if (status === "PASS" || status === "approved" || status === "fixed") return "good";
  if (status === "FAIL" || status === "UNRESOLVED" || status === "rejected") return "bad";
  if (status === "pending" || status === "NO CASES") return "warn";
  return "muted";
}

export function VerdictBadge({ status }: { status: string }) {
  const mark = status === "PASS" || status === "approved" || status === "fixed" ? "✓" : status === "FAIL" || status === "UNRESOLVED" || status === "rejected" ? "✕" : "•";
  return (
    <Badge tone={verdictTone(status)}>
      <span aria-hidden="true">{mark}</span>
      {status.toUpperCase()}
    </Badge>
  );
}

export function OracleBadge({ oracle }: { oracle: string }) {
  return oracle === "powerfx-engine" ? (
    <Badge tone="info" title="Expected value confirmed by Microsoft's Power Fx engine">
      Power Fx engine
    </Badge>
  ) : (
    <Badge tone="warn" title="Expected value written by hand">
      {oracle === "manual" ? "manual" : oracle}
    </Badge>
  );
}

export function Section({ title, subtitle, children, actions }: { title: string; subtitle?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] sm:p-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-3xl">
          <h2 className="text-[15px] font-semibold tracking-tight text-zinc-900">{title}</h2>
          {subtitle && <p className="mt-1 text-[13px] leading-5 text-zinc-500">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="text-2xs font-semibold uppercase tracking-wider text-zinc-400">{children}</h3>;
}

export function Diff({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l && !l.startsWith("+++") && !l.startsWith("---"));
  return (
    <pre className="overflow-x-auto rounded-lg bg-zinc-950 px-4 py-3 font-mono text-xs leading-5 text-zinc-300" aria-label="Unified diff">
      {lines.map((line, i) => {
        const kind = line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : "ctx";
        const cls = kind === "add" ? "-mx-4 px-4 bg-emerald-500/15 text-emerald-300" : kind === "del" ? "-mx-4 px-4 bg-red-500/15 text-red-300" : kind === "hunk" ? "text-indigo-300/80" : "";
        const label = kind === "add" ? "added: " : kind === "del" ? "removed: " : "";
        return (
          <div key={i} className={cls}>
            <span className="sr-only">{label}</span>
            {line}
          </div>
        );
      })}
    </pre>
  );
}

export function show(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) return `[${value.join(", ")}]`;
  if (typeof value === "string") return `"${value}"`;
  return String(value);
}

export function Stat({ label, value, detail, tone = "muted" }: { label: string; value: ReactNode; detail?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-lg border border-zinc-200/80 bg-white px-4 py-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
        <Dot tone={tone} />
        {label}
      </div>
      <div className={`mt-1 text-lg font-semibold tracking-tight ${values[tone]}`}>{value}</div>
      {detail && <div className="mt-0.5 truncate text-xs text-zinc-500" title={typeof detail === "string" ? detail : undefined}>{detail}</div>}
    </div>
  );
}

// Shared table classes, so every table reads the same.
export const th = "py-2 pr-4 text-left text-2xs font-semibold uppercase tracking-wider text-zinc-400";
export const td = "py-3 pr-4 align-top";
export const link = "font-mono font-semibold text-indigo-600 hover:text-indigo-800 hover:underline underline-offset-2";
export const buttonPrimary =
  "inline-flex items-center rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-zinc-700 disabled:opacity-40";
export const buttonGhost =
  "inline-flex items-center rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset ring-zinc-200 hover:bg-zinc-50 disabled:opacity-35";
