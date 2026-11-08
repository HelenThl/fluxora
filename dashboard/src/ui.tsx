// Small shared pieces. Colour is never the only signal: every badge also carries a word.
import type { ReactNode } from "react";

const tones = {
  good: "bg-emerald-50 text-emerald-800 ring-emerald-300",
  bad: "bg-red-50 text-red-800 ring-red-300",
  warn: "bg-amber-50 text-amber-900 ring-amber-300",
  info: "bg-sky-50 text-sky-900 ring-sky-300",
  muted: "bg-slate-100 text-slate-700 ring-slate-300",
} as const;
export type Tone = keyof typeof tones;

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-sm font-semibold ring-1 ring-inset ${tones[tone]}`}>
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
  const mark = status === "PASS" || status === "approved" || status === "fixed" ? "✓" : status === "FAIL" || status === "UNRESOLVED" || status === "rejected" ? "✗" : "•";
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
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{title}</h2>
          {subtitle && <p className="mt-1 text-slate-600">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Diff({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l && !l.startsWith("+++") && !l.startsWith("---"));
  return (
    <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-sm leading-6 text-slate-100" aria-label="Unified diff">
      {lines.map((line, i) => {
        const kind = line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : "ctx";
        const cls = kind === "add" ? "bg-emerald-900/60 text-emerald-200" : kind === "del" ? "bg-red-900/60 text-red-200" : kind === "hunk" ? "text-sky-300" : "";
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
    <div className={`rounded-lg p-4 ring-1 ring-inset ${tones[tone]}`}>
      <div className="text-sm font-medium opacity-80">{label}</div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
      {detail && <div className="mt-1 text-sm">{detail}</div>}
    </div>
  );
}
