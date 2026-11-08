"""fluxora: Transform. Rebuild. Verify."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from . import generate as rebuild
from . import register
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
