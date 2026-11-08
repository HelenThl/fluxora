import { useMemo, useState } from "react";
import type { ParityCase, RunData } from "../types";
import { Badge, Diff, OracleBadge, Section, Stat, VerdictBadge, show } from "../ui";

type Stage = "before" | "after";
const FIELDS = ["errors", "excess", "payable", "lateReport", "status"];
const SOURCE_LABEL: Record<string, string> = {
  "llm-api": "live LLM call",
  "llm-cache": "cached LLM response",
  "recorded-patch": "recorded patch",
  none: "no patch source",
};

export default function Verify({ run, onRule }: { run: RunData; onRule: (id: string) => void }) {
  const parity = run.parity;
  const hasBefore = Boolean(parity?.initial && parity.initial.failedCases.length);
  const [stage, setStage] = useState<Stage>(hasBefore ? "before" : "after");
  const [selected, setSelected] = useState<string | null>(null);

  const view = useMemo(() => {
    if (!parity) return null;
    if (stage === "after" || !parity.initial?.rules) {
      return { summary: parity.summary, ruleStatus: new Map(parity.rules.map((r) => [r.id, r.status])), cases: new Map(parity.cases.map((c) => [c.id, c])) };
    }
    const initialFailed = new Map(parity.initial.cases.map((c) => [c.id, c]));
    const cases = new Map<string, ParityCase>(parity.cases.map((c) => [c.id, initialFailed.get(c.id) ?? c]));
    return { summary: parity.initial.summary, ruleStatus: new Map(parity.initial.rules.map((r) => [r.id, r.status])), cases };
  }, [parity, stage]);

  if (!parity || !view) {
    return <Section title="Parity Court">Not judged yet. Run `fluxora judge {run.runId}`.</Section>;
  }

  const chosen = selected ? view.cases.get(selected) : null;
  const ev = run.evidence;
  return (
    <div className="space-y-6">
      <Section
        title="Parity Court"
        subtitle={
          <>
            Every reference case was sent to the migrated API and compared field by field with the original app's expected result.
            Judged {parity.judgedAt}.
          </>
        }
        actions={
          hasBefore && (
            <div role="group" aria-label="Which verdict to show" className="flex overflow-hidden rounded-lg ring-1 ring-slate-300">
              {(["before", "after"] as Stage[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={stage === s}
                  onClick={() => {
                    setStage(s);
                    setSelected(null);
                  }}
                  className={`px-4 py-2 font-semibold ${stage === s ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-100"}`}
                >
                  {s === "before" ? `Before repair (${parity.initial!.summary.result})` : `After repair (${parity.summary.result})`}
                </button>
              ))}
            </div>
          )
        }
      >
        <div
          className={`mb-4 flex flex-wrap items-center gap-4 rounded-lg p-4 ring-1 ring-inset ${
            view.summary.result === "PASS" ? "bg-emerald-50 ring-emerald-300" : "bg-red-50 ring-red-300"
          }`}
        >
          <span className={`text-3xl font-black ${view.summary.result === "PASS" ? "text-emerald-800" : "text-red-800"}`}>
            VERDICT: {view.summary.result}
          </span>
          <span className="text-lg">
            {view.summary.cases.passed}/{view.summary.cases.total} cases · {view.summary.rules.passed}/{view.summary.rules.total} rules pass
          </span>
          {parity.seededDefect && (
            <span className="text-slate-700">
              Seeded defect <span className="font-mono font-semibold">{parity.seededDefect.name}</span> in {parity.seededDefect.ruleId}:{" "}
              <code className="font-mono">{parity.seededDefect.before}</code> → <code className="font-mono">{parity.seededDefect.after}</code>
            </span>
          )}
        </div>

        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-slate-300 text-sm uppercase tracking-wide text-slate-500">
              <th className="py-2 pr-3">Rule</th>
              <th className="py-2 pr-3">Verdict</th>
              <th className="py-2">Reference cases (click one for expected vs actual)</th>
            </tr>
          </thead>
          <tbody>
            {parity.rules.map((rule) => {
              const status = view.ruleStatus.get(rule.id) ?? rule.status;
              const cases = [...view.cases.values()].filter((c) => c.ruleIds.includes(rule.id));
              return (
                <tr key={rule.id} className="border-b border-slate-200 align-top">
                  <td className="py-3 pr-3">
                    <button type="button" onClick={() => onRule(rule.id)} className="font-mono text-lg font-bold text-blue-700 underline" title={rule.rule}>
                      {rule.id}
                    </button>
                  </td>
                  <td className="py-3 pr-3">
                    <VerdictBadge status={status} />
                  </td>
                  <td className="py-3">
                    <div className="flex flex-wrap gap-2">
                      {cases.map((c) => {
                        const failing = !c.pass && c.implicatedRules.includes(rule.id);
                        return (
                          <button
                            key={c.id}
                            type="button"
                            aria-pressed={selected === c.id}
                            onClick={() => setSelected(selected === c.id ? null : c.id)}
                            className={`rounded-md px-2 py-1 text-left text-sm ring-1 ring-inset ${
                              failing ? "bg-red-50 text-red-900 ring-red-400" : c.pass ? "bg-emerald-50 text-emerald-900 ring-emerald-300" : "bg-slate-50 text-slate-700 ring-slate-300"
                            } ${selected === c.id ? "outline outline-2 outline-slate-900" : ""}`}
                          >
                            <span className="font-mono font-semibold">{c.id}</span>{" "}
                            <span className="font-bold">{c.pass ? "PASS" : failing ? "FAIL" : "FAIL (other rule)"}</span>
                            <span className="ml-1 opacity-70">· {c.oracle === "powerfx-engine" ? "Power Fx" : c.oracle}</span>
                          </button>
                        );
                      })}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {chosen && (
          <div className="mt-5 rounded-lg border border-slate-300 p-4" aria-live="polite">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="font-mono text-lg font-bold">{chosen.id}</h3>
              <VerdictBadge status={chosen.pass ? "PASS" : "FAIL"} />
              <OracleBadge oracle={chosen.oracle} />
              <span className="text-slate-700">{chosen.description}</span>
            </div>
            <p className="mt-1 text-sm text-slate-600">
              Rules: {chosen.ruleIds.join(", ")}
              {chosen.implicatedRules.length > 0 && <> · blamed: <strong>{chosen.implicatedRules.join(", ")}</strong></>}
            </p>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <div>
                <h4 className="font-semibold">Inputs</h4>
                <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
                  {Object.entries(chosen.inputs).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-slate-500">{k}</dt>
                      <dd className="font-mono">{show(v)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <div>
                <h4 className="font-semibold">Expected vs actual</h4>
                <table className="mt-1 w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500">
                      <th className="pr-2">Field</th>
                      <th className="pr-2">Expected (original app)</th>
                      <th className="pr-2">Actual (migrated)</th>
                      <th>Match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {FIELDS.map((f) => {
                      const differs = f in chosen.diff;
                      return (
                        <tr key={f} className={differs ? "bg-red-50 font-semibold text-red-900" : ""}>
                          <td className="pr-2 py-0.5">{f}</td>
                          <td className="pr-2 font-mono">{show(chosen.expected[f])}</td>
                          <td className="pr-2 font-mono">{show(chosen.actual[f])}</td>
                          <td>{differs ? "✗ differs" : "✓ same"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {chosen.actual.firedRules !== undefined && (
                  <p className="mt-2 text-sm text-slate-600">Rules the migrated app fired: {show(chosen.actual.firedRules)}</p>
                )}
              </div>
            </div>
          </div>
        )}
      </Section>

      <Section
        title="Repair attempts"
        subtitle="Each attempt is logged with its diff and an honest mode: live means a real LLM call in this run; replay means a cached response or a recorded patch."
      >
        {!run.repairs?.attempts.length ? (
          <p className="text-slate-600">No repairs were needed in this run.</p>
        ) : (
          <ol className="space-y-4">
            {run.repairs.attempts.map((a) => (
              <li key={`${a.ruleId}-${a.attempt}`} className="rounded-lg border border-slate-200 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-lg font-bold">
                    Attempt {a.attempt}/{run.repairs!.maxAttempts} · <span className="font-mono">{a.ruleId}</span>
                  </span>
                  <Badge tone={a.mode === "live" ? "info" : "warn"}>{a.mode.toUpperCase()}</Badge>
                  <span className="text-slate-700">{SOURCE_LABEL[a.source] ?? a.source}</span>
                  <VerdictBadge status={a.outcome === "fixed" ? "fixed" : a.outcome === "rejected" || a.outcome.includes("fail") ? "FAIL" : a.outcome} />
                  <span className="text-slate-700">{a.outcome}</span>
                </div>
                {a.provenance?.servedBy && (
                  <p className="mt-1 text-sm text-slate-600">
                    Provenance: {a.provenance.provider} · {a.provenance.servedBy}
                  </p>
                )}
                {a.judge && (
                  <p className="mt-1 text-sm text-slate-600">
                    Build {a.build}; re-judged {a.judge.casesPassed}/{a.judge.casesTotal} cases, {a.ruleId} {a.judge.ruleStatus}.
                  </p>
                )}
                {a.detail && <p className="mt-1 text-sm text-red-800">{a.detail}</p>}
                {a.diff && (
                  <div className="mt-3">
                    <Diff text={a.diff} />
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </Section>

      <Section title="Evidence summary" subtitle={<>Also written to <span className="font-mono">runs/{run.runId}/evidence.md</span> by <span className="font-mono">fluxora evidence {run.runId}</span>.</>}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Stat
            label="Human gate"
            value={`${ev.register.approved} approved`}
            detail={`${ev.register.rejected} rejected · ${ev.register.pending} pending · ${ev.register.decisions} timestamped decisions`}
            tone={ev.register.pending || ev.register.rejected ? "warn" : "good"}
          />
          <Stat
            label="Repairs"
            value={ev.repairs ? `${ev.repairs.attempts} attempt(s)` : "none"}
            detail={ev.repairs ? `fixed: ${ev.repairs.fixed.join(", ") || "-"} · unresolved: ${ev.repairs.unresolved.join(", ") || "-"}` : "no repairs needed"}
            tone={ev.repairs?.unresolved.length ? "bad" : "good"}
          />
          <Stat label="Unsupported items" value={ev.unsupported.length} detail={ev.unsupported.map((u) => u.construct).join(" · ")} tone="warn" />
          <Stat
            label="Oracle coverage"
            value={`${ev.oracle["powerfx-engine"] ?? 0} Power Fx engine`}
            detail={`${ev.oracle["manual"] ?? 0} manual expectations`}
            tone={ev.oracle["manual"] ? "warn" : "info"}
          />
          <Stat
            label="Tamper guard"
            value={ev.tamperGuard?.unchanged ? "Unchanged" : "CHANGED"}
            detail={ev.tamperGuard ? `reference-cases.json sha256 ${ev.tamperGuard.sha256Before.slice(0, 16)}…` : "not judged"}
            tone={ev.tamperGuard?.unchanged ? "good" : "bad"}
          />
          <Stat
            label="Last judge pass (measured)"
            value={ev.timings ? `${ev.timings.totalSeconds}s` : "-"}
            detail={ev.timings ? `build ${ev.timings.buildSeconds}s · start ${ev.timings.startupSeconds}s · cases ${ev.timings.casesSeconds}s` : undefined}
          />
        </div>
        <h3 className="mt-5 font-semibold">Data notes</h3>
        <ul className="mt-2 list-disc space-y-1 pl-6 text-slate-700">
          {ev.dataNotes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
