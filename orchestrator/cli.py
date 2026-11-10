"""fluxora: Transform. Rebuild. Verify."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import typer

from . import generate as rebuild
from . import judge as verify
from . import migrate as data_migration
from . import register, repair, serve as dashboard
from .evidence import generated_dir_for, write_evidence
from .extract import ExtractError, build_register
from .llm import LLMClient, LLMError, get_settings

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS = ROOT / "runs"
DEFAULT_GENERATED = ROOT / "generated"
DEMO_STAGES = 7

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


@app.command(help="Rebuild: migrate the Dataverse rows to Cosmos DB Claim documents, quarantine bad rows, reconcile. Writes migration.json.")
def migrate(
    run_id: str = typer.Argument(..., help="Run ID to migrate data for (uses its fixture and generated API)."),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
) -> None:
    path = register.rules_path(runs_dir, run_id)
    if not path.is_file():
        _fail(f"No register for run {run_id} at {path}")
    fixture = Path(register.load(path)["fixture"])
    fixture = fixture if fixture.is_absolute() else ROOT / fixture
    typer.echo(f"Rebuild: migrating {data_migration.RECORDS_FILE} to Cosmos DB documents for run {run_id}")
    try:
        report = data_migration.run_migration(fixture, generated_dir_for(path.parent, ROOT), path.parent)
    except data_migration.MigrationError as e:
        _fail(str(e))
    _print_migration(report)
    typer.echo(f"\nWrote {_display(path.parent / data_migration.DOCUMENTS_FILE)} and {_display(path.parent / data_migration.REPORT_FILE)}")
    raise typer.Exit(0 if report["result"] == "PASS" else 1)


def _print_migration(report: dict) -> None:
    c = report["counts"]
    typer.echo(f"Read {c['read']} rows from {report['source']['table']}: {c['migrated']} migrated, {c['quarantined']} quarantined.")
    for q in report["quarantined"]:
        typer.secho(f"  QUARANTINED  {q['claimId'] or q['record']}  {'; '.join(q['reasons'])}", fg=typer.colors.YELLOW)
    for d in report["defaulted"]:
        typer.echo(f"  defaulted    {d['column']} = {json.dumps(d['value'])} on row {d['record']} (schema default)")
    typer.echo("Reconciliation:")
    for check in report["reconciliation"]["checks"]:
        typer.secho(f"  {'PASS' if check['pass'] else 'FAIL'}", fg=typer.colors.GREEN if check["pass"] else typer.colors.RED, bold=True, nl=False)
        typer.echo(f"  {check['check']}: {check['detail']}")
    typer.secho(f"MIGRATION: {report['result']}", fg=typer.colors.GREEN if report["result"] == "PASS" else typer.colors.RED, bold=True)

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
    if verify.port_in_use(port):
        _fail(verify.port_in_use_message(port))
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


@app.command(help="Run the whole pipeline: Transform, approve, Rebuild (code and data), Verify (clean, then with the seeded defect and repair), evidence. Times every stage.")
def demo(
    pause: bool = typer.Option(False, "--pause", help="Wait for you to approve the rules in the dashboard instead of auto-approving."),
    offline: bool = typer.Option(False, "--offline", help="Never call an LLM; use only the committed cache and recorded patch."),
    port: int = typer.Option(verify.DEFAULT_PORT, "--port", help="Local port for the API under test."),
    runs_dir: Path = typer.Option(DEFAULT_RUNS, "--runs-dir", hidden=True),
) -> None:
    fixture = ROOT / "fixtures" / "claim-triage"
    # Fail before any work if the two things the Verify stages need are missing.
    if verify.port_in_use(port):
        _fail(verify.port_in_use_message(port))
    if shutil.which("dotnet") is None:
        _fail(verify.NO_DOTNET)
    client = LLMClient(get_settings(offline=offline), log=lambda _: None)
    stages: list[dict] = []
    demo_start = time.perf_counter()

    def begin(number: int, title: str) -> tuple[float, int, int]:
        typer.echo("")
        typer.secho(f"== {number}/{DEMO_STAGES}  {title} ==", bold=True)
        return time.perf_counter(), client.cache_hits, client.live_calls

    def finish(title: str, started: tuple[float, int, int], mode: str | None = None) -> None:
        seconds = time.perf_counter() - started[0]
        stages.append({"stage": title, "seconds": seconds, "mode": mode or _llm_mode(client.cache_hits - started[1], client.live_calls - started[2])})

    typer.secho("Fluxora demo: Transform. Rebuild. Verify.", bold=True)
    typer.echo(f"LLM: {client.mode}. Timings below are measured on this machine; each says whether an LLM answered live, from the cache, or by replay.")

    # 1. Transform: extract
    s = begin(1, "Transform: extract the rule register")
    try:
        extraction = build_register(fixture, client)
    except (ExtractError, LLMError) as e:
        _fail(str(e))
    extraction.register["fixture"] = "fixtures/claim-triage"
    run_id, rules_path = register.new_run(runs_dir, extraction.register)
    reg = extraction.register
    typer.echo(f"Run {run_id}: {len(reg['rules'])} rules, {len(reg['unsupported'])} unsupported items "
               f"({', '.join(u['construct'] for u in reg['unsupported'])}).")
    finish("Transform: extract", s)

    # 2. Transform: human gate
    s = begin(2, "Transform: human approval gate")
    if pause:
        if not (dashboard.DASHBOARD_DIST / "index.html").is_file():
            _fail("--pause needs the dashboard: cd dashboard && npm install && npm run build")
        server = dashboard.make_server(rules_path.parent, root=ROOT)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        typer.secho(f"Approve or reject each rule at http://127.0.0.1:{dashboard.DEFAULT_PORT}/#transform  (waiting; Ctrl+C aborts)", bold=True)
        try:
            while any(r["status"] == "pending" for r in register.load(rules_path)["rules"]):
                time.sleep(1)
        finally:
            server.shutdown()
            server.server_close()
        gate_mode = "human, in the dashboard (includes your decision time)"
    else:
        data = register.load(rules_path)
        register.approve(data, approve_all=True, reject=[])
        register.save(rules_path, data)
        gate_mode = "auto-approved, no human (use --pause to approve in the dashboard)"
        typer.secho("Human gate AUTO-APPROVED: all rules approved without review. Run `fluxora demo --pause` to approve them yourself.", fg=typer.colors.YELLOW)
    data = register.load(rules_path)
    approved = [r["id"] for r in data["rules"] if r["status"] == "approved"]
    rejected = [r["id"] for r in data["rules"] if r["status"] == "rejected"]
    typer.echo(f"Approved {len(approved)}; rejected {len(rejected)}{': ' + ', '.join(rejected) if rejected else ''}.")
    finish("Transform: approval gate", s, gate_mode)

    # 3. Rebuild
    s = begin(3, "Rebuild: generate the .NET API, Cosmos model, tests and React form")
    out = rules_path.parent / "generated"
    try:
        generation = rebuild.generate(data, client, root=ROOT)
    except (rebuild.GenerateError, ExtractError, LLMError) as e:
        _fail(str(e))
    rebuild.write(generation, out)
    compared = [p for p in generation.contents if p != "manifest.json" and (ROOT / "generated" / p).is_file()]
    same = [p for p in compared if (ROOT / "generated" / p).read_bytes() == generation.contents[p]]
    typer.echo(f"Wrote {len(generation.contents)} files to {_display(out)}/. "
               f"{len(same)}/{len(compared)} are byte-identical to the committed generated/ code "
               f"(manifest.json names the run, so it is not compared).")
    for p in sorted(set(compared) - set(same)):
        typer.secho(f"  differs from committed: {p}", fg=typer.colors.YELLOW)
    if generation.skipped:
        typer.secho("Skipped (not approved): " + ", ".join(f"{i} ({st})" for i, st in generation.skipped), fg=typer.colors.YELLOW)
    finish("Rebuild: generate", s)

    # 4. Rebuild: data migration
    s = begin(4, "Rebuild: migrate Dataverse rows to Cosmos DB documents and reconcile")
    try:
        migration = data_migration.run_migration(fixture, out, rules_path.parent)
    except data_migration.MigrationError as e:
        _fail(str(e))
    _print_migration(migration)
    finish("Rebuild: migrate data", s, "no LLM")

    def court(seed: str | None, printing: bool):
        def on_verdict(stage: str, verdict) -> None:
            if printing and stage == "initial":
                _print_court(verdict.parity, "PARITY COURT", "VERDICT" if verdict.passed else "Initial verdict")

        try:
            return repair.run_court(
                data, run_dir=rules_path.parent, client=client, seed=seed, port=port, source_api=out / "api",
                root=ROOT, log=lambda m: typer.echo(m) if printing and not m.startswith("  ") else None,
                on_verdict=on_verdict, on_attempt=_print_attempt if printing else None,
            )
        except (verify.JudgeError, repair.RepairError) as e:
            _fail(str(e))

    # 5. Verify: clean
    s = begin(5, "Verify: Parity Court on the generated code")
    clean = court(None, printing=False)
    summary = clean.parity["summary"]
    typer.secho(
        f"VERDICT: {summary['result']}  {summary['cases']['passed']}/{summary['cases']['total']} cases, "
        f"{summary['rules']['passed']}/{summary['rules']['total']} rules"
        + ("" if clean.passed else "  (see runs/" + run_id + "/parity-clean.json)"),
        fg=typer.colors.GREEN if clean.passed else typer.colors.RED, bold=True,
    )
    shutil.copyfile(rules_path.parent / "parity.json", rules_path.parent / "parity-clean.json")
    finish("Verify: judge clean code", s, _repair_mode(clean.attempts))

    # 6. Verify: seeded defect, repair
    s = begin(6, "Verify: seed a defect, watch Parity Court go red, repair, go green")
    seeded = court("threshold", printing=True)
    if seeded.attempts:
        _print_court(seeded.parity, "PARITY COURT  (after repair)", "Final verdict")
    fix = seeded.parity["repair"]
    if fix["fixed"]:
        typer.secho(f"Repaired {', '.join(fix['fixed'])} in {fix['attempts']} attempt(s) ({'; '.join(sorted({_mode_label(a) for a in seeded.attempts if a['outcome'] == 'fixed'}))}).",
                    fg=typer.colors.GREEN)
    if fix["unresolved"]:
        typer.secho(f"UNRESOLVED: {', '.join(fix['unresolved'])}", fg=typer.colors.RED, bold=True)
    finish("Verify: seeded defect + repair", s, _repair_mode(seeded.attempts))

    # 7. Evidence
    s = begin(7, "Evidence page")
    write_evidence(rules_path.parent, ROOT, demo_timings=stages)
    finish("Evidence: write evidence.md", s, "no LLM")
    total = time.perf_counter() - demo_start
    rows = stages + [{"stage": "Total", "seconds": total, "mode": ""}]
    evidence_path = write_evidence(rules_path.parent, ROOT, demo_timings=rows)
    typer.echo(f"Wrote {_display(evidence_path)}")

    typer.echo("")
    typer.secho("MEASURED TIMINGS (wall clock on this machine)", bold=True)
    width = max(len(r["stage"]) for r in rows)
    typer.echo(f"{'Stage':<{width}}  {'Seconds':>8}  Mode")
    for row in rows:
        typer.echo(f"{row['stage']:<{width}}  {row['seconds']:>8.2f}  {row['mode']}")
    passed = clean.passed and seeded.passed and migration["result"] == "PASS"
    typer.echo("")
    typer.secho(f"DEMO {'PASSED' if passed else 'FAILED'}: run {run_id}.  See it: fluxora serve {run_id}",
                fg=typer.colors.GREEN if passed else typer.colors.RED, bold=True)
    raise typer.Exit(0 if passed else 1)


@app.command(help="Pre-flight checks before a live demo: Python, .NET 8, NuGet cache, ports, LLM settings, offline cache, recorded patch.")
def doctor(
    port: int = typer.Option(verify.DEFAULT_PORT, "--port", help="Port the judge will use."),
    offline: bool = typer.Option(False, "--offline", help="Check for `fluxora demo --offline` (ignore a live key in .env)."),
) -> None:
    from .doctor import FAIL, OK, run_checks

    typer.secho("fluxora doctor: is this machine ready for `fluxora demo`?", bold=True)
    checks = run_checks(port=port, root=ROOT, offline=offline)
    width = max(len(name) for _, name, _ in checks)
    colours = {OK: typer.colors.GREEN, FAIL: typer.colors.RED}
    for status, name, detail in checks:
        typer.secho(f"{status:<5}", fg=colours.get(status, typer.colors.YELLOW), bold=True, nl=False)
        typer.echo(f" {name:<{width}}  {detail}")
    failed = [name for status, name, _ in checks if status == FAIL]
    typer.echo("")
    if failed:
        typer.secho(f"NOT READY: fix {', '.join(failed)}.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)
    warned = [name for status, name, _ in checks if status != OK]
    if warned:
        typer.secho(f"READY WITH WARNINGS: read {', '.join(warned)} above before presenting.", fg=typer.colors.YELLOW, bold=True)
        return
    typer.secho("READY: `fluxora demo` should run offline from the committed artefacts.", fg=typer.colors.GREEN, bold=True)


def _llm_mode(hits: int, live: int) -> str:
    if live and hits:
        return f"live LLM ({live} calls) + cached LLM ({hits} responses)"
    if live:
        return f"live LLM ({live} calls)"
    if hits:
        return f"cached LLM ({hits} responses, no API calls)"
    return "no LLM"


def _repair_mode(attempts: list[dict]) -> str:
    if not attempts:
        return "no LLM (no repair needed)"
    labels = {"llm-api": "live LLM", "llm-cache": "cached LLM", "recorded-patch": "replay", "none": "no patch source"}
    used = sorted({labels.get(a.get("source"), a.get("source", "?")) for a in attempts})
    return f"repair: {', '.join(used)} ({len(attempts)} attempt(s))"


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
