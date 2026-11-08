"""fluxora: Transform. Rebuild. Verify."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from . import generate as rebuild
from . import judge as verify
from . import register, repair, serve as dashboard
from .evidence import write_evidence
from .extract import ExtractError, build_register
from .llm import LLMClient, LLMError, get_settings

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS = ROOT / "runs"
DEFAULT_GENERATED = ROOT / "generated"

app = typer.Typer(
    help="Fluxora: Transform. Rebuild. Verify. Migrate a Power App and prove it behaves the same, rule by rule.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    _load_dotenv(ROOT / ".env")


def _load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines into the environment without printing anything. Real env vars win."""
    if os.environ.get("FLUXORA_NO_DOTENV") or not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _fail(message: str) -> None:
    typer.secho(f"error: {message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(1)


@app.command(help="Transform: read the Power App export and write the rule register to runs/<run-id>/rules.json.")
def extract(
    fixture_dir: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder with the app export."),
    offline: bool = typer.Option(False, "--offline", help="Serve LLM text only from the committed cache."),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
) -> None:
    client = LLMClient(get_settings(offline=offline), log=typer.echo)
    typer.echo(f"Transform: extracting rules from {fixture_dir.as_posix()}  [LLM: {client.mode}]")
    try:
        result = build_register(fixture_dir, client)
    except (ExtractError, LLMError) as e:
        _fail(str(e))
    run_id, path = register.new_run(runs_dir, result.register)
    reg = result.register

    typer.echo("")
    width = max(len("Output"), *(len(r["output"]) for r in reg["rules"]))
    typer.echo(f"{'ID':<4} {'Output':<{width}} {'Conf':<7} Rule")
    for rule in reg["rules"]:
        typer.echo(f"{rule['id']:<4} {rule['output']:<{width}} {rule['confidence']:<7} {rule['rule']}")
    typer.echo("")
    typer.echo("Precedence: " + " > ".join("+".join(group) for group in reg["precedence"]))
    typer.echo(f"Unsupported ({len(reg['unsupported'])}):")
    for item in reg["unsupported"]:
        typer.echo(f"  {item['file']} {item['ref']}: {item['construct']}")
    for warning in result.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW)
    typer.echo(f"Not migrated as rules: {result.ignored_properties} layout, styling and display properties.")
    typer.echo(f"LLM: {client.cache_hits} cache hit(s), {client.live_calls} live call(s).")
    typer.echo(f"\nWrote {_display(path)}")
    typer.echo(f"Run ID: {run_id}")


@app.command(help="Rebuild: generate the .NET API, Cosmos model, tests and React form from the approved rules.")
def generate(
    run_id: str = typer.Argument(..., help="Run ID whose approved rules.json to build from."),
    offline: bool = typer.Option(False, "--offline", help="Serve LLM text only from the committed cache."),
    out: Path = typer.Option(DEFAULT_GENERATED, "--out", help="Output folder (default: generated/)."),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
) -> None:
    path = register.rules_path(runs_dir, run_id)
    if not path.is_file():
        _fail(f"No register for run {run_id} at {path}")
    data = register.load(path)
    client = LLMClient(get_settings(offline=offline), log=typer.echo)
    typer.echo(f"Rebuild: generating from run {run_id}  [LLM: {client.mode}]")
    try:
        result = rebuild.generate(data, client, root=ROOT)
    except (rebuild.GenerateError, ExtractError, LLMError) as e:
        _fail(str(e))
    rebuild.write(result, out)

    if result.skipped:
        typer.secho(
            "Skipped (not approved): " + ", ".join(f"{i} ({s})" for i, s in result.skipped), fg=typer.colors.YELLOW
        )
    typer.echo("")
    width = max(len(p) for p in result.files)
    typer.echo(f"{'File':<{width}}  Rules")
    for file, ids in result.files.items():
        typer.echo(f"{file:<{width}}  {', '.join(ids) or '-'}")
    typer.echo("")
    typer.echo(f"LLM: {client.cache_hits} cache hit(s), {client.live_calls} live call(s).")
    typer.echo(f"Wrote {len(result.files)} files to {_display(out)}/")


@app.command(help="Verify: judge the migrated API against every reference case, repair failing rules (max 3 attempts), write parity.json and repairs.json.")
def judge(
    run_id: str = typer.Argument(..., help="Run ID whose register to judge."),
    seed_defect: str = typer.Option(None, "--seed-defect", help="Break a rule on purpose in the working copy first. Known: threshold."),
    offline: bool = typer.Option(False, "--offline", help="Repair only from the committed cache or a recorded patch."),
    port: int = typer.Option(verify.DEFAULT_PORT, "--port", help="Local port for the API under test."),
    api_dir: Path = typer.Option(verify.DEFAULT_API_DIR, "--api-dir", hidden=True),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
    recorded_dir: Path = typer.Option(repair.RECORDED_DIR, "--recorded-dir", hidden=True),
) -> None:
    path = register.rules_path(runs_dir, run_id)
    if not path.is_file():
        _fail(f"No register for run {run_id} at {path}")
    data = register.load(path)
    client = LLMClient(get_settings(offline=offline), log=lambda _: None)
    typer.echo(f"Verify: Parity Court for run {run_id}  [repair LLM: {client.mode}]")

    def on_verdict(stage: str, verdict) -> None:
        if stage == "initial":
            _print_court(verdict.parity, "PARITY COURT", "VERDICT" if verdict.passed else "Initial verdict")

    try:
        result = repair.run_court(
            data,
            run_dir=path.parent,
            client=client,
            seed=seed_defect,
            port=port,
            source_api=api_dir,
            recorded_dir=recorded_dir,
            root=ROOT,
            log=lambda m: typer.echo(m) if not m.startswith("  ") else None,
            on_verdict=on_verdict,
            on_attempt=_print_attempt,
        )
    except (verify.JudgeError, repair.RepairError) as e:
        _fail(str(e))

    if result.attempts:
        _print_court(result.parity, "PARITY COURT  (after repair)", "Final verdict")
    guard = result.parity["tamperGuard"]
    if not guard["unchanged"]:
        typer.secho(f"TAMPER GUARD: {guard['message']}", fg=typer.colors.RED, bold=True)
    fix = result.parity["repair"]
    if fix["fixed"]:
        sources = sorted({_mode_label(a) for a in result.attempts if a["outcome"] == "fixed"})
        typer.secho(
            f"Repaired {', '.join(fix['fixed'])} in {fix['attempts']} attempt(s) ({'; '.join(sources)}).",
            fg=typer.colors.GREEN,
        )
    if fix["unresolved"]:
        typer.secho(f"UNRESOLVED after {fix['maxAttempts']} attempts: {', '.join(fix['unresolved'])}", fg=typer.colors.RED, bold=True)
    typer.echo(f"\nWrote {_display(path.parent / 'parity.json')} and {_display(path.parent / 'repairs.json')}")
    raise typer.Exit(0 if result.passed else 1)


@app.command(help="Verify: write runs/<run-id>/evidence.md (register, approvals, parity, repairs, unsupported items, oracle coverage, timings).")
def evidence(
    run_id: str = typer.Argument(..., help="Run ID to write the evidence page for."),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
) -> None:
    run_dir = runs_dir / run_id
    if not (run_dir / register.RULES_FILE).is_file():
        _fail(f"No register for run {run_id} at {run_dir}")
    path = write_evidence(run_dir, ROOT)
    typer.echo(f"Wrote {_display(path)}")


@app.command(help="Open the dashboard (Transform / Rebuild / Verify) for a run on http://127.0.0.1:8765.")
def serve(
    run_id: str = typer.Argument(None, help="Run ID to show (default: the latest run)."),
    port: int = typer.Option(dashboard.DEFAULT_PORT, "--port", help="Local port for the dashboard."),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
) -> None:
    run_id = run_id or dashboard.latest_run(runs_dir)
    if not run_id or not (runs_dir / run_id / register.RULES_FILE).is_file():
        _fail(f"No run to show{f' ({run_id})' if run_id else ''}. Run `fluxora extract` first.")
    if not (dashboard.DASHBOARD_DIST / "index.html").is_file():
        typer.secho("Dashboard not built yet: cd dashboard && npm install && npm run build", fg=typer.colors.YELLOW)
    try:
        server = dashboard.make_server(runs_dir / run_id, port=port, root=ROOT)
    except OSError as e:
        _fail(f"Could not listen on 127.0.0.1:{port}: {e}")
    typer.secho(f"Fluxora dashboard for run {run_id}: http://127.0.0.1:{port}/", bold=True)
    typer.echo("Transform. Rebuild. Verify.  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    finally:
        server.server_close()


def _mode_label(attempt: dict) -> str:
    return {
        "llm-api": "live LLM call",
        "llm-cache": "replay: cached LLM response",
        "recorded-patch": "replay: recorded patch",
    }.get(attempt.get("source"), attempt.get("source", "?"))


def _print_attempt(attempt: dict) -> None:
    typer.echo("")
    typer.secho(
        f"REPAIR  {attempt['ruleId']}  attempt {attempt['attempt']}/{repair.MAX_ATTEMPTS}  [{_mode_label(attempt)}]",
        bold=True,
    )
    for line in (attempt.get("diff") or "").splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        colour = typer.colors.GREEN if line.startswith("+") else typer.colors.RED if line.startswith("-") else None
        if colour:
            typer.secho(f"  {line.rstrip()}", fg=colour)
    outcome = attempt["outcome"]
    judged = attempt.get("judge")
    detail = f"  cases {judged['casesPassed']}/{judged['casesTotal']}" if judged else f"  {attempt.get('detail', '')[:200]}"
    typer.secho(f"  -> {outcome}{detail}", fg=typer.colors.GREEN if outcome == "fixed" else typer.colors.RED)


def _print_court(parity: dict, heading: str = "PARITY COURT", verdict_label: str = "VERDICT") -> None:
    colours = {"PASS": typer.colors.GREEN, "FAIL": typer.colors.RED, "UNRESOLVED": typer.colors.RED, "NO CASES": typer.colors.YELLOW}
    ref = parity["referenceCases"]
    typer.echo("")
    typer.secho(f"{heading}  -  run {parity['runId']}", bold=True)
    typer.echo(
        f"Reference cases: {ref['path']}  sha256 {ref['sha256Before'][:12]}  "
        + ("(unchanged)" if ref["unchanged"] else "(CHANGED DURING THE RUN)")
    )
    typer.echo(f"API under test:  {parity['api']['project']} at {parity['api']['url']}")
    typer.echo("")
    typer.echo(f"{'Rule':<5} {'Cases':<6} {'Verdict':<9} {'Oracle':<15} What the rule says")
    typer.echo(f"{'-' * 5} {'-' * 6} {'-' * 9} {'-' * 15} {'-' * 48}")
    cases = {c["id"]: c for c in parity["cases"]}
    for rule in parity["rules"]:
        passed = rule["casesTotal"] - rule["casesFailed"]
        sentence = rule["rule"] if len(rule["rule"]) <= 60 else rule["rule"][:57] + "..."
        typer.echo(f"{rule['id']:<5} {f'{passed}/{rule['casesTotal']}':<6} ", nl=False)
        typer.secho(f"{rule['status']:<9}", fg=colours.get(rule["status"]), bold=True, nl=False)
        typer.echo(f" {rule['oracle']:<15} {sentence}")
        for case_id in rule["failedCases"]:
            for name, d in cases[case_id]["diff"].items():
                typer.secho(
                    f"      {case_id}  {name}: expected {json.dumps(d['expected'])}, got {json.dumps(d['actual'])}",
                    fg=typer.colors.RED,
                )
    s, t = parity["summary"], parity["timings"]
    typer.echo("")
    typer.echo(
        f"Cases {s['cases']['passed']}/{s['cases']['total']} pass   Rules {s['rules']['passed']}/{s['rules']['total']} pass   "
        f"Time: build {t['buildSeconds']}s, start {t['startupSeconds']}s, cases {t['casesSeconds']}s"
    )
    typer.secho(f"{verdict_label.upper()}: {s['result']}", fg=colours[s["result"]], bold=True)


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


@app.command(help="Transform: approve or reject rules in the register (CLI fallback for the dashboard gate).")
def approve(
    run_id: str = typer.Argument(..., help="Run ID printed by `fluxora extract`."),
    approve_all: bool = typer.Option(False, "--all", help="Approve every rule that is not rejected."),
    reject: str = typer.Option("", "--reject", help="Comma-separated rule IDs to reject, e.g. R05,R06."),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
) -> None:
    path = register.rules_path(runs_dir, run_id)
    if not path.is_file():
        _fail(f"No register for run {run_id} at {path}")
    data = register.load(path)
    rejected = [r.strip().upper() for r in reject.split(",") if r.strip()]
    try:
        decisions = register.approve(data, approve_all=approve_all, reject=rejected)
    except ValueError as e:
        _fail(str(e))
    register.save(path, data)
    approved = [d["ruleId"] for d in decisions if d["decision"] == "approved"]
    typer.echo(f"Approved {len(approved)}: {', '.join(approved) or '-'}")
    typer.echo(f"Rejected {len(rejected)}: {', '.join(rejected) or '-'}")
    typer.echo(f"Recorded at {decisions[0]['at'] if decisions else '-'} in {path.name}")


if __name__ == "__main__":
    app()
