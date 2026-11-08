import { useEffect, useState } from "react";
import type { RunData } from "../types";
import { Badge, Section, VerdictBadge } from "../ui";

const confidenceTone = { high: "good", medium: "warn", low: "bad" } as const;

export default function Transform({ run, focus, onChange }: { run: RunData; focus: string | null; onChange: () => Promise<void> }) {
  const register = run.rules;
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const lastDecision = new Map(register.approvals.map((a) => [a.ruleId, a]));
  const pending = register.rules.filter((r) => r.status !== "approved").length;

  useEffect(() => {
    if (focus) document.getElementById(`rule-${focus}`)?.scrollIntoView({ block: "center" });
  }, [focus]);

  async function decide(body: { approve?: string[]; reject?: string[]; all?: boolean }, label: string) {
    setBusy(label);
    setMessage(null);
    try {
      const response = await fetch("/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? `HTTP ${response.status}`);
      await onChange();
      setMessage(`Recorded ${result.decisions.length} decision(s) in rules.json.`);
    } catch (e) {
      setMessage(`Not recorded: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <Section
        title="Rule Register"
        subtitle={
          <>
            {register.rules.length} rules extracted from <span className="font-mono">{register.fixture}</span>. Only approved rules flow to Rebuild.
            Precedence: <span className="font-mono">{register.precedence.map((g) => g.join("+")).join(" > ")}</span>
          </>
        }
        actions={
          <button
            type="button"
            onClick={() => decide({ all: true }, "all")}
            disabled={busy !== null}
            className="rounded-lg bg-emerald-700 px-4 py-2 font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
          >
            {busy === "all" ? "Approving…" : `Approve all${pending ? ` (${pending} not yet approved)` : ""}`}
          </button>
        }
      >
        {message && (
          <p role="status" className="mb-3 rounded-md bg-slate-100 px-3 py-2 text-slate-800">
            {message}
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-slate-300 text-sm uppercase tracking-wide text-slate-500">
                <th className="py-2 pr-3">ID</th>
                <th className="py-2 pr-3">Rule (plain English)</th>
                <th className="py-2 pr-3">Formula</th>
                <th className="py-2 pr-3">Source</th>
                <th className="py-2 pr-3">Confidence</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2">Decision</th>
              </tr>
            </thead>
            <tbody>
              {register.rules.map((rule) => {
                const decided = lastDecision.get(rule.id);
                return (
                  <tr
                    key={rule.id}
                    id={`rule-${rule.id}`}
                    className={`border-b border-slate-200 align-top ${focus === rule.id ? "bg-amber-50" : ""}`}
                  >
                    <td className="py-3 pr-3 font-mono font-bold">{rule.id}</td>
                    <td className="max-w-md py-3 pr-3">{rule.rule}</td>
                    <td className="max-w-xs py-3 pr-3">
                      <code className="break-words font-mono text-sm text-slate-700">{rule.formula}</code>
                    </td>
                    <td className="max-w-xs py-3 pr-3 text-sm">
                      <div className="font-semibold">{rule.source.file}</div>
                      <div className="break-all font-mono text-slate-600">{rule.source.ref}</div>
                    </td>
                    <td className="py-3 pr-3">
                      <Badge tone={confidenceTone[rule.confidence]}>{rule.confidence}</Badge>
                    </td>
                    <td className="py-3 pr-3">
                      <VerdictBadge status={rule.status} />
                      {decided && <div className="mt-1 whitespace-nowrap text-xs text-slate-500">{decided.at}</div>}
                    </td>
                    <td className="py-3">
                      <div className="flex gap-2">
                        <button
                          type="button"
                          aria-label={`Approve ${rule.id}`}
                          disabled={busy !== null || rule.status === "approved"}
                          onClick={() => decide({ approve: [rule.id] }, rule.id)}
                          className="rounded-md border border-emerald-600 px-3 py-1 font-semibold text-emerald-800 hover:bg-emerald-50 disabled:opacity-40"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          aria-label={`Reject ${rule.id}`}
                          disabled={busy !== null || rule.status === "rejected"}
                          onClick={() => decide({ reject: [rule.id] }, rule.id)}
                          className="rounded-md border border-red-600 px-3 py-1 font-semibold text-red-800 hover:bg-red-50 disabled:opacity-40"
                        >
                          Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-sm text-slate-600">
          Sentences and confidence: {register.ruleTextModel}. Everything else in the register is parsed from the fixture by code.
          Every decision is appended to <span className="font-mono">rules.json</span> with a UTC timestamp ({register.approvals.length} so far).
        </p>
      </Section>

      <Section
        title="Unsupported items"
        subtitle="The extractor saw these but cannot migrate them. They are listed, never dropped."
      >
        <ul className="space-y-3">
          {register.unsupported.map((item) => (
            <li key={`${item.file}#${item.ref}`} className="rounded-lg border border-amber-300 bg-amber-50 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="warn">UNSUPPORTED</Badge>
                <code className="font-mono font-semibold">{item.construct}</code>
                <span className="text-sm text-slate-600">
                  {item.file} <span className="font-mono">{item.ref}</span>
                </span>
              </div>
              <p className="mt-2">{item.reason}</p>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
