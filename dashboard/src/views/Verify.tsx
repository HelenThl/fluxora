import { useMemo, useState } from "react";
import type { Migration, ParityCase, RunData } from "../types";
import { Badge, Diff, Dot, OracleBadge, Section, Stat, SubHeading, VerdictBadge, link, show, td, th } from "../ui";

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
    <div className="space-y-5">
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
            <div role="group" aria-label="Which verdict to show" className="flex gap-1 rounded-lg bg-zinc-100 p-1">
              {(["before", "after"] as Stage[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={stage === s}
                  onClick={() => {
                    setStage(s);
                    setSelected(null);
                  }}
                  className={`rounded-md px-3 py-1 text-xs font-medium ${stage === s ? "bg-white text-zinc-900 shadow-sm ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-900"}`}
                >
                  {s === "before" ? `Before repair (${parity.initial!.summary.result})` : `After repair (${parity.summary.result})`}
                </button>
              ))}
            </div>
          )
        }
      >
        <div
          className={`mb-5 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg px-4 py-3 ring-1 ring-inset ${
            view.summary.result === "PASS" ? "bg-emerald-50/60 ring-emerald-600/15" : "bg-red-50/70 ring-red-600/15"
          }`}
        >
          <span className={`flex items-center gap-2 text-base font-semibold tracking-tight ${view.summary.result === "PASS" ? "text-emerald-700" : "text-red-700"}`}>
            <Dot tone={view.summary.result === "PASS" ? "good" : "bad"} />
            Verdict: {view.summary.result}
          </span>
          <span className="text-[13px] text-zinc-600">
            {view.summary.cases.passed}/{view.summary.cases.total} cases · {view.summary.rules.passed}/{view.summary.rules.total} rules pass
          </span>
          {parity.seededDefect && (
            <span className="text-xs text-zinc-500">
              Seeded defect <span className="font-mono font-semibold">{parity.seededDefect.name}</span> in {parity.seededDefect.ruleId}:{" "}
              <code className="font-mono">{parity.seededDefect.before}</code> → <code className="font-mono">{parity.seededDefect.after}</code>
            </span>
          )}
        </div>

        <table className="w-full border-collapse text-left text-[13px] leading-5">
          <thead>
            <tr className="border-b border-zinc-200">
              <th className={`${th} w-16`}>Rule</th>
              <th className={`${th} w-24`}>Verdict</th>
              <th className={th}>Reference cases · click one for expected vs actual</th>
            </tr>
          </thead>
          <tbody>
            {parity.rules.map((rule) => {
              const status = view.ruleStatus.get(rule.id) ?? rule.status;
              const cases = [...view.cases.values()].filter((c) => c.ruleIds.includes(rule.id));
              return (
                <tr key={rule.id} className="border-b border-zinc-100 last:border-0">
                  <td className={td}>
                    <button type="button" onClick={() => onRule(rule.id)} className={`text-xs ${link}`} title={rule.rule}>
                      {rule.id}
                    </button>
                  </td>
                  <td className={td}>
                    <VerdictBadge status={status} />
                  </td>
                  <td className="py-2.5 align-top">
                    <div className="flex flex-wrap gap-1">
                      {cases.map((c) => {
                        const failing = !c.pass && c.implicatedRules.includes(rule.id);
                        return (
                          <button
                            key={c.id}
                            type="button"
                            aria-pressed={selected === c.id}
                            onClick={() => setSelected(selected === c.id ? null : c.id)}
                            title={`${c.id}: ${c.description}`}
                            className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs ring-1 ring-inset transition-colors ${
                              failing
                                ? "bg-red-50 text-red-700 ring-red-600/30 hover:bg-red-100"
                                : c.pass
                                  ? "bg-white text-zinc-600 ring-zinc-200 hover:bg-zinc-50"
                                  : "bg-zinc-50 text-zinc-500 ring-zinc-300 hover:bg-zinc-100"
                            } ${selected === c.id ? "!ring-2 !ring-zinc-900" : ""}`}
                          >
                            <span aria-hidden="true" className={failing ? "text-red-600" : c.pass ? "text-emerald-600" : "text-zinc-400"}>
                              {c.pass ? "✓" : "✕"}
                            </span>
                            <span className="font-mono font-medium">{c.id}</span>
                            <span className="sr-only">{c.pass ? "PASS" : failing ? "FAIL" : "FAIL (other rule)"}</span>
                            {!c.pass && <span className="font-medium">{failing ? "FAIL" : "other rule"}</span>}
                            <span className="text-zinc-400">· {c.oracle === "powerfx-engine" ? "Power Fx" : c.oracle}</span>
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
          <div className="mt-5 rounded-lg border border-zinc-200 bg-zinc-50/50 p-4" aria-live="polite">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="font-mono text-sm font-semibold text-zinc-900">{chosen.id}</h3>
              <VerdictBadge status={chosen.pass ? "PASS" : "FAIL"} />
              <OracleBadge oracle={chosen.oracle} />
              <span className="text-[13px] text-zinc-600">{chosen.description}</span>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              Rules: {chosen.ruleIds.join(", ")}
              {chosen.implicatedRules.length > 0 && <> · blamed: <strong>{chosen.implicatedRules.join(", ")}</strong></>}
            </p>
            <div className="mt-4 grid gap-6 md:grid-cols-2">
              <div>
                <SubHeading>Inputs</SubHeading>
                <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-0.5 text-xs">
                  {Object.entries(chosen.inputs).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-zinc-500">{k}</dt>
                      <dd className="font-mono text-zinc-800">{show(v)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <div>
                <SubHeading>Expected vs actual</SubHeading>
                <table className="mt-2 w-full text-xs">
                  <thead>
                    <tr className="text-left text-2xs uppercase tracking-wider text-zinc-400">
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
                        <tr key={f} className={differs ? "bg-red-50 font-medium text-red-700" : "text-zinc-700"}>
                          <td className="py-1 pr-2">{f}</td>
                          <td className="pr-2 font-mono">{show(chosen.expected[f])}</td>
                          <td className="pr-2 font-mono">{show(chosen.actual[f])}</td>
                          <td>{differs ? "✗ differs" : "✓ same"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {chosen.actual.firedRules !== undefined && (
                  <p className="mt-2 text-xs text-zinc-500">Rules the migrated app fired: {show(chosen.actual.firedRules)}</p>
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
          <p className="text-[13px] text-zinc-500">No repairs were needed in this run.</p>
        ) : (
          <ol className="space-y-3">
            {run.repairs.attempts.map((a) => (
              <li key={`${a.ruleId}-${a.attempt}`} className="rounded-lg border border-zinc-200/80 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold text-zinc-900">
                    Attempt {a.attempt}/{run.repairs!.maxAttempts} · <span className="font-mono">{a.ruleId}</span>
                  </span>
                  <Badge tone={a.mode === "live" ? "info" : "warn"}>{a.mode.toUpperCase()}</Badge>
                  <span className="text-xs text-zinc-500">{SOURCE_LABEL[a.source] ?? a.source}</span>
                  <VerdictBadge status={a.outcome === "fixed" ? "fixed" : a.outcome === "rejected" || a.outcome.includes("fail") ? "FAIL" : a.outcome} />
                  <span className="text-xs text-zinc-500">{a.outcome}</span>
                </div>
                {a.provenance?.servedBy && (
                  <p className="mt-1.5 text-xs text-zinc-500">
                    Provenance: {a.provenance.provider} · {a.provenance.servedBy}
                  </p>
                )}
                {a.judge && (
                  <p className="mt-0.5 text-xs text-zinc-500">
                    Build {a.build}; re-judged {a.judge.casesPassed}/{a.judge.casesTotal} cases, {a.ruleId} {a.judge.ruleStatus}.
                  </p>
                )}
                {a.detail && <p className="mt-1 text-xs text-red-700">{a.detail}</p>}
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

      {ev.migration && <MigrationSection m={ev.migration} runId={run.runId} />}

      <Section title="Evidence summary" subtitle={<>Also written to <span className="font-mono">runs/{run.runId}/evidence.md</span> by <span className="font-mono">fluxora evidence {run.runId}</span>.</>}>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
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
            label="Data migration"
            value={ev.migration ? (ev.migration.replay && ev.migration.replay.result !== "PASS" ? ev.migration.replay.result : ev.migration.result) : "not run"}
            detail={
              ev.migration
                ? `${ev.migration.counts.migrated} migrated · ${ev.migration.counts.quarantined} quarantined${ev.migration.replay ? ` · replay ${ev.migration.replay.matched}/${ev.migration.replay.compared}` : ""}`
                : `run: fluxora migrate ${run.runId}`
            }
            tone={!ev.migration ? "muted" : ev.migration.result === "PASS" && (!ev.migration.replay || ev.migration.replay.result === "PASS") ? "good" : "bad"}
          />
          <Stat
            label="Last judge pass (measured)"
            value={ev.timings ? `${ev.timings.totalSeconds}s` : "-"}
            detail={ev.timings ? `build ${ev.timings.buildSeconds}s · start ${ev.timings.startupSeconds}s · cases ${ev.timings.casesSeconds}s` : undefined}
          />
        </div>
        <div className="mt-6">
          <SubHeading>Data notes</SubHeading>
        </div>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-zinc-600 marker:text-zinc-300">
          {ev.dataNotes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

function MigrationSection({ m, runId }: { m: Migration; runId: string }) {
  return (
    <Section
      title="Data migration"
      subtitle={
        <>
          Dataverse <span className="font-mono">{m.source.table}</span> rows to Cosmos DB documents (
          <span className="font-mono">{m.target.document}</span>, id = <span className="font-mono">{m.target.id}</span>, partition key{" "}
          <span className="font-mono">{m.target.partitionKey}</span>). Written to <span className="font-mono">runs/{runId}/{m.target.file}</span>.
        </>
      }
    >
      <div className="grid gap-2 sm:grid-cols-3">
        <Stat label="Rows read" value={m.counts.read} detail={m.source.path} tone="info" />
        <Stat label="Migrated" value={m.counts.migrated} detail="mapped from dataverse-schema.json" tone="good" />
        <Stat label="Quarantined" value={m.counts.quarantined} detail="not migrated; a person must decide" tone={m.counts.quarantined ? "warn" : "good"} />
      </div>
      <div className="mt-6 flex items-center gap-2">
        <SubHeading>Reconciliation</SubHeading>
        <VerdictBadge status={m.result} />
      </div>
      <ul className="mt-2 divide-y divide-zinc-100 rounded-lg border border-zinc-200/80 text-[13px]">
        {m.checks.map((c) => (
          <li key={c.check} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2">
            <span className={`w-12 shrink-0 whitespace-nowrap text-2xs font-semibold ${c.pass ? "text-emerald-600" : "text-red-600"}`}>{c.pass ? "✓ PASS" : "✕ FAIL"}</span>
            <span className="shrink-0 font-medium text-zinc-800 sm:w-64">{c.check}</span>
            <span className="min-w-0 text-zinc-500">{c.detail}</span>
          </li>
        ))}
      </ul>
      {m.quarantined.length > 0 && (
        <>
          <div className="mt-6">
            <SubHeading>Quarantined rows</SubHeading>
          </div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-zinc-200">
                  <th className={th}>Claim ID</th>
                  <th className={th}>Reasons</th>
                </tr>
              </thead>
              <tbody>
                {m.quarantined.map((q) => (
                  <tr key={q.record} className="border-b border-zinc-100 align-top last:border-0">
                    <td className="whitespace-nowrap py-2 pr-4 font-mono text-xs text-zinc-900">{q.claimId ?? q.record}</td>
                    <td className="py-2 text-zinc-600">{q.reasons.join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {m.replay && (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-2">
            <SubHeading>Replay through the migrated app</SubHeading>
            <VerdictBadge status={m.replay.result} />
            <span className="text-xs text-zinc-500">
              {m.replay.matched}/{m.replay.compared} statuses match Dataverse · each claim evaluated as of its {m.replay.asOf}
            </span>
          </div>
          {m.replay.mismatched.length > 0 && (
            <table className="mt-2 w-full text-left text-[13px] leading-5">
              <thead>
                <tr className="border-b border-zinc-200">
                  <th className={th}>Claim</th>
                  <th className={th}>Dataverse</th>
                  <th className={th}>Migrated app</th>
                </tr>
              </thead>
              <tbody>
                {m.replay.mismatched.map((x) => (
                  <tr key={x.id} className="border-b border-zinc-100 bg-red-50/60 text-red-700 last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">{x.id}</td>
                    <td className="py-2 pr-4">{x.stored ?? "-"}</td>
                    <td className="py-2 pr-4">{x.errors.length ? `errors ${x.errors.join(", ")}` : x.migratedApp ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {m.replay.noStoredStatus.length > 0 && (
            <p className="mt-2 text-xs text-zinc-500">
              Not compared (no status stored in Dataverse):{" "}
              {m.replay.noStoredStatus.map((x) => `${x.id} (migrated app: ${x.migratedApp ?? "-"})`).join(" · ")}
            </p>
          )}
        </>
      )}
      {m.defaulted.length > 0 && (
        <p className="mt-4 text-xs text-zinc-500">
          Defaulted (empty in Dataverse, schema default applied):{" "}
          {m.defaulted.map((d) => `${d.column} = ${JSON.stringify(d.value)}`).join(" · ")}
        </p>
      )}
    </Section>
  );
}
