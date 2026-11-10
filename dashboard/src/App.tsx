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

  const current = VIEWS.find((v) => v.id === view);
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-zinc-200/80 bg-white/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-6 px-6">
          <div className="flex items-center gap-2.5">
            <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-md bg-zinc-900 text-[13px] font-bold text-white">
              F
            </span>
            <div className="leading-tight">
              <h1 className="text-sm font-semibold tracking-tight text-zinc-900">Fluxora</h1>
              <p className="text-2xs text-zinc-500">Transform. Rebuild. Verify.</p>
            </div>
          </div>
          <nav aria-label="Pipeline stages" className="flex items-center gap-1 rounded-lg bg-zinc-100 p-1">
            {VIEWS.map((v, i) => (
              <a
                key={v.id}
                href={`#${v.id}`}
                aria-current={view === v.id ? "page" : undefined}
                className={`rounded-md px-3 py-1 text-[13px] font-medium transition-colors ${
                  view === v.id ? "bg-white text-zinc-900 shadow-sm ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-900"
                }`}
              >
                <span className="mr-1.5 font-mono text-2xs text-zinc-400">{i + 1}</span>
                {v.label}
              </a>
            ))}
          </nav>
          <div className="hidden text-right text-2xs leading-4 text-zinc-500 md:block">
            {run && (
              <>
                <div>
                  Run <span className="font-mono font-medium text-zinc-800">{run.runId}</span>
                </div>
                <div className="font-mono">{run.rules.fixture}</div>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 px-6 pb-16 pt-6">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-zinc-900">{current?.label}</h2>
          <p className="text-[13px] text-zinc-500">{current?.blurb}</p>
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-[13px] font-medium text-red-700 ring-1 ring-inset ring-red-600/20">
            {error}
          </p>
        )}
        {!run && !error && <p className="text-zinc-500">Loading run…</p>}
        {run && view === "transform" && <Transform run={run} focus={focus} onChange={load} />}
        {run && view === "rebuild" && <Rebuild run={run} onRule={(id) => go("transform", id)} />}
        {run && view === "verify" && <Verify run={run} onRule={(id) => go("transform", id)} />}
      </main>
    </div>
  );
}
