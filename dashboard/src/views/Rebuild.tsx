import { useState } from "react";
import type { RunData } from "../types";
import { Badge, Section } from "../ui";

const GROUPS: { title: string; subtitle: string; match: (path: string) => boolean }[] = [
  { title: "api/Rules", subtitle: "One file per approved rule. The method body came from the LLM; everything else is deterministic.", match: (p) => p.startsWith("api/Rules/") },
  { title: "api/Data", subtitle: "Cosmos DB Claim document and repositories (InMemory by default).", match: (p) => p.startsWith("api/Data/") },
  { title: "api (wiring and tests)", subtitle: "Evaluator applies the extracted precedence; tests run every reference case.", match: (p) => p.startsWith("api/") },
  { title: "web", subtitle: "The React form that mirrors ClaimScreen.", match: (p) => p.startsWith("web/") },
];

export default function Rebuild({ run, onRule }: { run: RunData; onRule: (id: string) => void }) {
  const manifest = run.manifest;
  const [open, setOpen] = useState<Record<string, string | null>>({});
  const sentence = new Map(run.rules.rules.map((r) => [r.id, r.rule]));

  if (!manifest) {
    return <Section title="Generated code">Nothing generated yet. Run `fluxora generate {run.runId}`.</Section>;
  }

  async function toggle(path: string) {
    if (open[path] !== undefined) {
      setOpen(({ [path]: _, ...rest }) => rest);
      return;
    }
    const response = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
    const body = await response.json();
    setOpen((o) => ({ ...o, [path]: response.ok ? body.content : `Could not load: ${body.error}` }));
  }

  const remaining = new Set(manifest.files.map((f) => f.path).filter((p) => p !== "manifest.json"));
  return (
    <div className="space-y-6">
      <Section
        title="Generated code"
        subtitle={
          <>
            {manifest.files.length} files in <span className="font-mono">generated/</span> from run{" "}
            <span className="font-mono">{manifest.generatedFrom.runId}</span>. Rule bodies: {manifest.ruleBodyModel}.
            {manifest.skipped.length > 0 && <> Skipped (not approved): {manifest.skipped.map((s) => `${s.id} (${s.status})`).join(", ")}.</>}
            {manifest.note && <> Note: {manifest.note}.</>}
          </>
        }
      >
        <div className="space-y-8">
          {GROUPS.map((group) => {
            const files = [...remaining].filter(group.match).sort();
            files.forEach((p) => remaining.delete(p));
            if (!files.length) return null;
            return (
              <div key={group.title}>
                <h3 className="font-mono text-lg font-semibold">{group.title}</h3>
                <p className="mb-3 text-slate-600">{group.subtitle}</p>
                <ul className="grid gap-3 md:grid-cols-2">
                  {files.map((path) => {
                    const rules = manifest.files.find((f) => f.path === path)?.rules ?? [];
                    const isRule = path.startsWith("api/Rules/");
                    return (
                      <li key={path} className="rounded-lg border border-slate-200 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono font-semibold">{path.split("/").pop()}</span>
                          <button type="button" onClick={() => toggle(path)} className="text-sm font-semibold text-blue-700 underline">
                            {open[path] !== undefined ? "Hide source" : "View source"}
                          </button>
                        </div>
                        {isRule && rules[0] && (
                          <p className="mt-1 text-slate-700">
                            <a
                              href={`#transform/${rules[0]}`}
                              onClick={() => onRule(rules[0])}
                              className="mr-2 font-mono font-bold text-blue-700 underline"
                              title="Open this rule in the Transform view"
                            >
                              Rule {rules[0]}
                            </a>
                            {sentence.get(rules[0])}
                          </p>
                        )}
                        {!isRule && rules.length > 0 && (
                          <p className="mt-1 text-sm text-slate-600">
                            Implements: {rules.map((id) => (
                              <Badge key={id} tone="muted">{id}</Badge>
                            ))}
                          </p>
                        )}
                        {open[path] !== undefined && (
                          <pre className="mt-3 max-h-96 overflow-auto rounded-md bg-slate-900 p-3 font-mono text-sm text-slate-100">{open[path]}</pre>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}
