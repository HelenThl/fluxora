import { useEffect, useState } from "react";
import type { RunData } from "../types";
import { Badge, Section, VerdictBadge, buttonGhost, buttonPrimary, td, th } from "../ui";

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
    <div className="space-y-5">
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
            className={buttonPrimary}
          >
            {busy === "all" ? "Approving…" : `Approve all${pending ? ` (${pending} not yet approved)` : ""}`}
          </button>
        }
      >
        {message && (
          <p role="status" className="mb-4 rounded-md bg-zinc-50 px-3 py-2 text-[13px] text-zinc-700 ring-1 ring-inset ring-zinc-200">
            {message}
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[13px] leading-5">
            <thead>
              <tr className="border-b border-zinc-200">
                <th className={th}>ID</th>
                <th className={th}>Rule (plain English)</th>
                <th className={th}>Formula</th>
                <th className={th}>Source</th>
                <th className={th}>Confidence</th>
                <th className={th}>Status</th>
                <th className={th}>Decision</th>
              </tr>
            </thead>
            <tbody>
              {register.rules.map((rule) => {
                const decided = lastDecision.get(rule.id);
                return (
                  <tr
                    key={rule.id}
                    id={`rule-${rule.id}`}
                    className={`border-b border-zinc-100 last:border-0 ${focus === rule.id ? "bg-amber-50/70" : "hover:bg-zinc-50/60"}`}
                  >
                    <td className={`${td} font-mono text-xs font-semibold text-zinc-900`}>{rule.id}</td>
                    <td className={`${td} max-w-md text-zinc-800`}>{rule.rule}</td>
                    <td className={`${td} max-w-xs`}>
                      <code className="box-decoration-clone break-words rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs leading-6 text-zinc-700">{rule.formula}</code>
                    </td>
                    <td className={`${td} max-w-xs text-xs`}>
                      <div className="font-medium text-zinc-700">{rule.source.file}</div>
                      <div className="break-all font-mono text-2xs text-zinc-400">{rule.source.ref}</div>
                    </td>
                    <td className={td}>
                      <Badge tone={confidenceTone[rule.confidence]}>{rule.confidence}</Badge>
                    </td>
                    <td className={td}>
                      <VerdictBadge status={rule.status} />
                      {decided && <div className="mt-1 whitespace-nowrap font-mono text-2xs text-zinc-400">{decided.at}</div>}
                    </td>
                    <td className="py-3 align-top">
                      <div className="flex gap-1.5">
                        <button
                          type="button"
                          aria-label={`Approve ${rule.id}`}
                          disabled={busy !== null || rule.status === "approved"}
                          onClick={() => decide({ approve: [rule.id] }, rule.id)}
                          className={`${buttonGhost} text-emerald-700`}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          aria-label={`Reject ${rule.id}`}
                          disabled={busy !== null || rule.status === "rejected"}
                          onClick={() => decide({ reject: [rule.id] }, rule.id)}
                          className={`${buttonGhost} text-red-700`}
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
        <p className="mt-4 text-xs leading-5 text-zinc-500">
          Sentences and confidence: {register.ruleTextModel}. Everything else in the register is parsed from the fixture by code.
          Every decision is appended to <span className="font-mono">rules.json</span> with a UTC timestamp ({register.approvals.length} so far).
        </p>
      </Section>

      <Section
        title="Unsupported items"
        subtitle="The extractor saw these but cannot migrate them. They are listed, never dropped."
      >
        <ul className="divide-y divide-zinc-100 overflow-hidden rounded-lg border border-zinc-200/80">
          {register.unsupported.map((item) => (
            <li key={`${item.file}#${item.ref}`} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="warn">UNSUPPORTED</Badge>
                <code className="font-mono text-[13px] font-medium text-zinc-900">{item.construct}</code>
                <span className="text-xs text-zinc-400">
                  {item.file} <span className="font-mono">{item.ref}</span>
                </span>
              </div>
              <p className="mt-1 text-[13px] text-zinc-600">{item.reason}</p>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
