import { useCallback, useEffect, useState } from "react";
import type { RunData } from "./types";
import Transform from "./views/Transform";
import Rebuild from "./views/Rebuild";
import Verify from "./views/Verify";

type View = "transform" | "rebuild" | "verify";

const VIEWS: { id: View; label: string; blurb: string }[] = [
  { id: "transform", label: "Transform", blurb: "Rule register and human approval" },
  { id: "rebuild", label: "Rebuild", blurb: "Generated code, traced to rule IDs" },
  { id: "verify", label: "Verify", blurb: "Parity Court and evidence" },
];

function readHash(): { view: View; focus: string | null } {
  const [view, focus] = window.location.hash.replace(/^#/, "").split("/");
  return { view: VIEWS.some((v) => v.id === view) ? (view as View) : "transform", focus: focus || null };
}

export default function App() {
  const [{ view, focus }, setLocation] = useState(readHash);
  const [run, setRun] = useState<RunData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/run");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setRun((await response.json()) as RunData);
      setError(null);
    } catch (e) {
      setError(`Could not load the run from fluxora serve (${(e as Error).message}).`);
    }
  }, []);

  useEffect(() => {
    load();
    const onHash = () => setLocation(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [load]);

  const go = (target: View, rule?: string) => {
    window.location.hash = rule ? `${target}/${rule}` : target;
  };

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Fluxora</h1>
            <p className="text-lg font-medium text-slate-600">Transform. Rebuild. Verify.</p>
          </div>
          <nav aria-label="Pipeline stages" className="flex gap-2">
            {VIEWS.map((v, i) => (
              <a
                key={v.id}
                href={`#${v.id}`}
                aria-current={view === v.id ? "page" : undefined}
                className={`rounded-lg px-4 py-2 text-lg font-semibold ${
                  view === v.id ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <span className="mr-1 text-sm opacity-70">{i + 1}.</span>
                {v.label}
              </a>
            ))}
          </nav>
          {run && (
            <div className="text-right text-sm text-slate-600">
              <div>
                Run <span className="font-mono font-semibold text-slate-900">{run.runId}</span>
              </div>
              <div>{run.rules.fixture}</div>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        <p className="text-slate-600">{VIEWS.find((v) => v.id === view)?.blurb}</p>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 p-4 font-medium text-red-800 ring-1 ring-red-300">
            {error}
          </p>
        )}
        {!run && !error && <p>Loading run…</p>}
        {run && view === "transform" && <Transform run={run} focus={focus} onChange={load} />}
        {run && view === "rebuild" && <Rebuild run={run} onRule={(id) => go("transform", id)} />}
        {run && view === "verify" && <Verify run={run} onRule={(id) => go("transform", id)} />}
      </main>
    </div>
  );
}
