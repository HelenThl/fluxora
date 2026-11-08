"""Evidence: one summary of a run, shared by `fluxora evidence` (evidence.md) and the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from .register import now_iso

ROOT = Path(__file__).resolve().parent.parent
GENERATED_MANIFEST = ROOT / "generated" / "manifest.json"


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_run(run_dir: Path, root: Path = ROOT) -> dict:
    """Everything the dashboard needs for one run, plus the evidence summary."""
    rules = _load(run_dir / "rules.json")
    if rules is None:
        raise FileNotFoundError(f"No rules.json in {run_dir}")
    parity = _load(run_dir / "parity.json")
    repairs = _load(run_dir / "repairs.json")
    generated_dir = generated_dir_for(run_dir, root)
    manifest = _load(generated_dir / "manifest.json")
    if manifest and manifest.get("generatedFrom", {}).get("runId") != rules.get("runId"):
        manifest = manifest | {"note": f"generated/ was built from run {manifest['generatedFrom'].get('runId')}"}
    fixture = Path(rules["fixture"])
    cases = _load((fixture if fixture.is_absolute() else root / fixture) / "reference-cases.json")
    try:
        generated_label = generated_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        generated_label = generated_dir.as_posix()
    return {
        "runId": rules.get("runId"),
        "rules": rules,
        "parity": parity,
        "repairs": repairs,
        "manifest": manifest,
        "generatedDir": generated_label,
        "evidence": summarize(rules, parity, repairs, manifest, cases),
    }


def generated_dir_for(run_dir: Path, root: Path = ROOT) -> Path:
    """A run made by `fluxora demo` keeps its own generated/ folder; otherwise use the committed one."""
    own = run_dir / "generated"
    return own if (own / "manifest.json").is_file() else root / "generated"


def summarize(rules: dict, parity: dict | None, repairs: dict | None, manifest: dict | None, cases: dict | None) -> dict:
    statuses = [r["status"] for r in rules["rules"]]
    oracle: dict[str, int] = {}
    for case in (cases or {}).get("cases", []):
        oracle[case.get("oracle", "manual")] = oracle.get(case.get("oracle", "manual"), 0) + 1

    modes: dict[str, int] = {}
    for attempt in (repairs or {}).get("attempts", []):
        key = f"{attempt.get('mode')}:{attempt.get('source')}"
        modes[key] = modes.get(key, 0) + 1

    notes = []
    meta = (cases or {}).get("meta", {})
    if meta.get("synthetic"):
        notes.append("All data is synthetic: no real names, policy numbers or personal data anywhere in the fixture.")
    total_cases = sum(oracle.values())
    if total_cases:
        notes.append(
            f"{oracle.get('powerfx-engine', 0)} of {total_cases} expected results were confirmed by Microsoft's Power Fx "
            f"engine; {oracle.get('manual', 0)} rely on hand-written values."
        )
    if str(rules.get("ruleTextModel", "")).startswith("claude-code:"):
        notes.append("Rule sentences were written in a Claude Code session from the extractor's prompts, not by a live API call.")
    if manifest and str(manifest.get("ruleBodyModel", "")).startswith("claude-code:"):
        notes.append("C# rule bodies were written in a Claude Code session from the generator's prompts, not by a live API call.")
    for attempt in (repairs or {}).get("attempts", []):
        if attempt.get("mode") == "replay":
            notes.append(
                f"Repair attempt {attempt['attempt']} for {attempt['ruleId']} was a replay ({attempt.get('source')}), not a live LLM call."
            )

    summary = {
        "runId": rules.get("runId"),
        "fixture": rules.get("fixture"),
        "register": {
            "rules": len(statuses),
            "approved": statuses.count("approved"),
            "rejected": statuses.count("rejected"),
            "pending": statuses.count("pending"),
            "decisions": len(rules.get("approvals", [])),
            "lastDecisionAt": max((a["at"] for a in rules.get("approvals", [])), default=None),
        },
        "unsupported": rules.get("unsupported", []),
        "oracle": oracle,
        "parity": None,
        "repairs": None,
        "tamperGuard": None,
        "timings": None,
        "dataNotes": notes,
    }
    if parity:
        summary["parity"] = {
            "result": parity["summary"]["result"],
            "cases": parity["summary"]["cases"],
            "rules": parity["summary"]["rules"],
            "judgedAt": parity.get("judgedAt"),
            "seededDefect": parity.get("seededDefect"),
            "initial": (parity.get("initial") or {}).get("summary"),
            "initialRedRules": (parity.get("initial") or {}).get("redRules", []),
        }
        summary["tamperGuard"] = parity.get("tamperGuard") or {
            "unchanged": parity["referenceCases"]["unchanged"],
            "sha256Before": parity["referenceCases"]["sha256Before"],
            "sha256After": parity["referenceCases"]["sha256After"],
        }
        summary["timings"] = parity.get("timings")
    if repairs:
        summary["repairs"] = {
            "attempts": len(repairs.get("attempts", [])),
            "fixed": repairs.get("fixed", []),
            "unresolved": repairs.get("unresolved", []),
            "modes": modes,
        }
    return summary


# --- evidence.md ----------------------------------------------------------------------------------


def _cell(value: object) -> str:
    return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")


def render_markdown(run: dict, demo_timings: list[dict] | None = None) -> str:
    rules, parity, repairs, ev = run["rules"], run["parity"], run["repairs"], run["evidence"]
    decided = {}
    for a in rules.get("approvals", []):
        decided[a["ruleId"]] = a
    out = [
        f"# Fluxora evidence: run {run['runId']}",
        "",
        "**Transform. Rebuild. Verify.**",
        "",
        f"Written {now_iso()} by `fluxora evidence {run['runId']}`, from `runs/{run['runId']}/`.",
        "",
        "## Summary",
        "",
        f"- **Transform:** {ev['register']['rules']} rules extracted from `{ev['fixture']}`. "
        f"{ev['register']['approved']} approved, {ev['register']['rejected']} rejected, {ev['register']['pending']} pending "
        f"({ev['register']['decisions']} timestamped decisions). {len(ev['unsupported'])} unsupported constructs are listed below.",
    ]
    if run.get("manifest"):
        files = run["manifest"]["files"]
        rule_files = [f for f in files if f["path"].startswith("api/Rules/")]
        out.append(
            f"- **Rebuild:** {len(files)} files generated under `{run.get('generatedDir', 'generated')}/`, including "
            f"{len(rule_files)} rule files, each traceable to one rule ID."
        )
    p = ev["parity"]
    if p:
        line = f"- **Verify:** Parity Court **{p['result']}**: {p['cases']['passed']}/{p['cases']['total']} cases and {p['rules']['passed']}/{p['rules']['total']} rules."
        if p.get("seededDefect"):
            sd, init = p["seededDefect"], p["initial"]
            line += (
                f" Seeded defect `{sd['name']}` in {sd['ruleId']} made the first verdict {init['result']} "
                f"({init['cases']['passed']}/{init['cases']['total']} cases; red: {', '.join(p['initialRedRules']) or '-'})."
            )
        out.append(line)
    if ev["repairs"]:
        r = ev["repairs"]
        out.append(
            f"- **Repair:** {r['attempts']} attempt(s); fixed {', '.join(r['fixed']) or '-'}; unresolved {', '.join(r['unresolved']) or '-'}."
        )
    guard = ev.get("tamperGuard")
    if guard:
        out.append(f"- **Tamper guard:** reference cases {'unchanged' if guard['unchanged'] else 'CHANGED'} (sha256 `{guard['sha256Before'][:16]}`).")

    out += ["", "## Rule register", "", "| ID | Rule | Formula | Source | Confidence | Status | Decided |", "|---|---|---|---|---|---|---|"]
    for r in rules["rules"]:
        d = decided.get(r["id"])
        out.append(
            f"| {r['id']} | {_cell(r['rule'])} | `{_cell(r['formula'])}` | {_cell(r['source']['file'])} `{_cell(r['source']['ref'])}` "
            f"| {r['confidence']} | {r['status']} | {d['at'] if d else '-'} |"
        )

    if parity:
        out += ["", "## Parity Court", "", "| Rule | Cases | Verdict | Oracle |", "|---|---|---|---|"]
        for r in parity["rules"]:
            out.append(f"| {r['id']} | {r['casesTotal'] - r['casesFailed']}/{r['casesTotal']} | {r['status']} | {r['oracle']} |")
        failing = [c for c in parity["cases"] if not c["pass"]]
        initial = (parity.get("initial") or {}).get("cases", [])
        for title, group in (("Failing cases (initial verdict)", initial), ("Failing cases (final verdict)", failing)):
            if group:
                out += ["", f"**{title}:**", ""]
                for c in group:
                    for name, diff in c["diff"].items():
                        out.append(
                            f"- {c['id']} (rules {', '.join(c['implicatedRules'])}): {name} expected "
                            f"`{json.dumps(diff['expected'])}`, got `{json.dumps(diff['actual'])}` [oracle: {c['oracle']}]"
                        )

    if repairs and repairs.get("attempts"):
        out += ["", "## Repair log", ""]
        for a in repairs["attempts"]:
            judged = a.get("judge") or {}
            out.append(
                f"### Attempt {a['attempt']}: {a['ruleId']} ({a['mode']}, {a['source']}): {a['outcome']}"
            )
            out.append("")
            prov = a.get("provenance") or {}
            if prov:
                out.append(f"Provenance: provider `{prov.get('provider')}`, model `{prov.get('model')}`. {prov.get('servedBy') or ''}".rstrip())
                out.append("")
            if judged:
                out.append(f"Build {a.get('build')}; judge {judged.get('result')} ({judged.get('casesPassed')}/{judged.get('casesTotal')} cases).")
                out.append("")
            if a.get("diff"):
                out += ["```diff", a["diff"].rstrip("\n"), "```", ""]
            elif a.get("detail"):
                out += [f"Detail: {_cell(a['detail'])}", ""]

    out += ["", "## Unsupported items", "", "| File | Ref | Construct | Reason |", "|---|---|---|---|"]
    for u in ev["unsupported"]:
        out.append(f"| {_cell(u['file'])} | `{_cell(u['ref'])}` | `{_cell(u['construct'])}` | {_cell(u['reason'])} |")

    out += ["", "## Oracle coverage", "", "| Oracle | Cases |", "|---|---|"]
    for name, count in sorted(ev["oracle"].items()):
        out.append(f"| {name} | {count} |")

    timings = ev.get("timings")
    if timings or demo_timings:
        out += ["", "## Timings (measured wall-clock)", ""]
        if demo_timings:
            out += ["| Stage | Seconds | Mode |", "|---|---|---|"]
            out += [f"| {t['stage']} | {t['seconds']:.2f} | {t['mode']} |" for t in demo_timings]
            out.append("")
        if timings:
            out.append(
                f"Last judge pass: build {timings.get('buildSeconds')}s, API start {timings.get('startupSeconds')}s, "
                f"cases {timings.get('casesSeconds')}s."
            )

    out += ["", "## Data notes", ""]
    out += [f"- {n}" for n in ev["dataNotes"]] or ["- None."]
    return "\n".join(out) + "\n"


def write_evidence(run_dir: Path, root: Path = ROOT, demo_timings: list[dict] | None = None) -> Path:
    run = load_run(run_dir, root)
    path = run_dir / "evidence.md"
    path.write_text(render_markdown(run, demo_timings), encoding="utf-8", newline="\n")
    return path
