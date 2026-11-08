"""Seeded defect, repair loop and tamper guard. Integration tests need the .NET 8 SDK (port 5091)."""

import json
import shutil

import pytest
from typer.testing import CliRunner

from orchestrator import cli, register, repair
from orchestrator.llm import LLMClient, Settings, get_settings
from orchestrator.repair import Patch, RepairError, apply_patch, run_court, seed_defect, validate_patch

from .conftest import FIXTURE, ROOT

PORT = 5091
RUN_ID = "20261108-143433"
COMMITTED_RUN = ROOT / "runs" / RUN_ID / "rules.json"
API_DIR = ROOT / "generated" / "api"
CLEAN_R09 = (API_DIR / "Rules" / "R09.cs").read_text(encoding="utf-8")
GOOD_REPLY = "FILE: Rules/R09.cs\n```csharp\n" + CLEAN_R09 + "```\n"

needs_dotnet = pytest.mark.skipif(shutil.which("dotnet") is None, reason="needs the .NET 8 SDK")


def client_with(tmp_path, replies):
    """A 'live' client whose provider answers with the given replies in order (or a function)."""
    queue = list(replies) if not callable(replies) else None

    def transport(settings, system, prompt):
        text = replies(prompt) if queue is None else queue.pop(0)
        return text, "fake-model"

    settings = Settings(provider="anthropic", api_key="test-key", model="fake-model", base_url=None, offline=False)
    return LLMClient(settings, cache_dir=tmp_path / "cache", transport=transport, log=lambda _: None)


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    """One run folder shared by the integration tests, so bin/obj are reused and builds stay quick."""
    folder = tmp_path_factory.mktemp("runs") / RUN_ID
    folder.mkdir()
    shutil.copy(COMMITTED_RUN, folder / "rules.json")
    return folder


def court(run_dir, client, tmp_path, **kwargs):
    kwargs.setdefault("recorded_dir", tmp_path / "recorded")
    return run_court(register.load(COMMITTED_RUN), run_dir=run_dir, client=client, port=PORT, log=lambda _: None, **kwargs)


# --- seeded defect precision (no dotnet needed) ---------------------------------------------------


def test_seed_changes_exactly_one_operator(tmp_path):
    work = repair.prepare_working_copy(API_DIR, tmp_path / "api")
    seeded = seed_defect(work, "threshold")
    assert seeded["before"] == "return (claimAmount ?? 0m) > 5000m;"
    assert seeded["after"] == "return (claimAmount ?? 0m) >= 5000m;"
    text = (work / "Rules" / "R09.cs").read_text(encoding="utf-8")
    assert "// Formula: ClaimAmount > 5000" in text  # the header comment is not touched
    assert (API_DIR / "Rules" / "R09.cs").read_text(encoding="utf-8") == CLEAN_R09  # committed code untouched


@pytest.mark.parametrize("body", ["return claimAmount == 5000m;", "return claimAmount > 1m && claimAmount > 5000m;"])
def test_seed_refuses_to_guess(tmp_path, body):
    work = repair.prepare_working_copy(API_DIR, tmp_path / "api")
    rule_file = work / "Rules" / "R09.cs"
    rule_file.write_text(CLEAN_R09.replace("return (claimAmount ?? 0m) > 5000m;", body), encoding="utf-8")
    with pytest.raises(RepairError, match="exactly one"):
        seed_defect(work, "threshold")


# --- patch validation and scope (no dotnet needed) ------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["../Program.cs", "Rules/../Program.cs", "/tmp/Rules/R09.cs", "C:/work/Rules/R09.cs", "Rules/R04.cs", "Rules/sub/R09.cs", "Program.cs"],
)
def test_patch_outside_the_rule_file_is_rejected(path):
    reply = f"FILE: {path}\n```csharp\n{CLEAN_R09}```\n"
    with pytest.raises(RepairError):
        validate_patch(Patch("live", "llm-api", {}, reply=reply), "R09", CLEAN_R09)


@pytest.mark.parametrize(
    "content, reason",
    [
        (CLEAN_R09.replace("Applies(decimal? claimAmount)", "Applies(decimal claimAmount)"), "signature"),
        (CLEAN_R09.replace("// Rule R09\n", "", 1), "// Rule R09"),
        (CLEAN_R09.replace("> 5000m", "> 5000m && claimId != \"CLM-000124\""), "claim or policy"),
    ],
)
def test_patch_that_breaks_the_contract_is_rejected(content, reason):
    with pytest.raises(RepairError, match=reason):
        validate_patch(Patch("live", "llm-api", {}, reply=f"FILE: Rules/R09.cs\n```csharp\n{content}```\n"), "R09", CLEAN_R09)


def test_apply_refuses_to_write_outside_rules(tmp_path):
    work = repair.prepare_working_copy(API_DIR, tmp_path / "api")
    before = (work / "Program.cs").read_text(encoding="utf-8")
    with pytest.raises(RepairError, match="Refusing"):
        apply_patch(work, "../api/Program.cs", "hacked", "R09")
    assert (work / "Program.cs").read_text(encoding="utf-8") == before


# --- the court run (real API) ---------------------------------------------------------------------


@needs_dotnet
def test_seeded_defect_goes_red_on_5000_then_repair_turns_it_green(run_dir, tmp_path):
    result = court(run_dir, client_with(tmp_path, [GOOD_REPLY]), tmp_path, seed="threshold")

    failed = [c for c in result.first.parity["cases"] if not c["pass"]]
    assert [c["id"] for c in failed] == ["R09-02"]
    assert failed[0]["inputs"]["claimAmount"] == 5000.0
    assert failed[0]["implicatedRules"] == ["R09"]
    assert result.parity["initial"]["redRules"] == ["R09"]

    assert result.passed and result.parity["summary"]["result"] == "PASS"
    assert [(a["outcome"], a["mode"], a["source"]) for a in result.attempts] == [("fixed", "live", "llm-api")]
    assert "-        return (claimAmount ?? 0m) >= 5000m;" in result.attempts[0]["diff"]
    assert (tmp_path / "recorded" / "repair-R09.json").is_file()  # first successful LLM repair is recorded
    assert (API_DIR / "Rules" / "R09.cs").read_text(encoding="utf-8") == CLEAN_R09


@needs_dotnet
def test_three_bad_patches_leave_r09_unresolved_and_exit_nonzero(run_dir, tmp_path, monkeypatch):
    bad = [
        "FILE: ../Program.cs\n```csharp\n// Rule R09\nbroken\n```\n",  # outside Rules/: rejected
        f"FILE: Rules/R09.cs\n```csharp\n{CLEAN_R09.replace('> 5000m', '>= 5000m')}```\n",  # builds, still wrong
        f"FILE: Rules/R09.cs\n```csharp\n{CLEAN_R09.replace('return (claimAmount', 'retrun (claimAmount')}```\n",  # no build
    ]
    fake = client_with(tmp_path, bad)
    monkeypatch.setattr(cli, "LLMClient", lambda settings, log: fake)
    program_before = (API_DIR / "Program.cs").read_text(encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        ["judge", RUN_ID, "--seed-defect", "threshold", "--port", str(PORT),
         "--runs-dir", str(run_dir.parent), "--recorded-dir", str(tmp_path / "recorded")],
    )
    assert result.exit_code != 0, result.output
    assert "UNRESOLVED" in result.output

    repairs = json.loads((run_dir / "repairs.json").read_text(encoding="utf-8"))
    assert [a["outcome"] for a in repairs["attempts"]] == ["rejected", "still failing", "build failed"]
    assert repairs["unresolved"] == ["R09"]
    parity = json.loads((run_dir / "parity.json").read_text(encoding="utf-8"))
    assert next(r for r in parity["rules"] if r["id"] == "R09")["status"] == "UNRESOLVED"
    assert parity["summary"]["result"] == "FAIL"
    assert (run_dir / "work" / "api" / "Program.cs").read_text(encoding="utf-8") == program_before
    assert not (tmp_path / "recorded" / "repair-R09.json").exists()


@needs_dotnet
def test_changing_reference_cases_mid_run_trips_the_guard(run_dir, tmp_path):
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    data = register.load(COMMITTED_RUN) | {"fixture": str(fixture)}

    def tamper_then_fix(prompt):
        cases = fixture / "reference-cases.json"
        cases.write_text(cases.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return GOOD_REPLY

    result = run_court(
        data, run_dir=run_dir, client=client_with(tmp_path, tamper_then_fix), seed="threshold",
        port=PORT, recorded_dir=tmp_path / "recorded", log=lambda _: None,
    )
    guard = result.parity["tamperGuard"]
    assert guard["unchanged"] is False and guard["sha256Before"] != guard["sha256After"]
    assert "changed during the run" in guard["message"]
    assert not result.passed and result.parity["summary"]["result"] == "FAIL"


@needs_dotnet
def test_offline_seeded_flow_replays_the_recorded_patch(run_dir, tmp_path):
    recorded = tmp_path / "recorded"
    shutil.copytree(repair.RECORDED_DIR, recorded)
    offline = LLMClient(
        Settings(provider=None, api_key=None, model=None, base_url=None, offline=True),
        cache_dir=tmp_path / "empty-cache",
        log=lambda _: None,
    )
    result = court(run_dir, offline, tmp_path, seed="threshold", recorded_dir=recorded)
    assert result.passed
    assert [(a["mode"], a["source"]) for a in result.attempts] == [("replay", "recorded-patch")]


@needs_dotnet
def test_committed_cache_repairs_the_demo_offline(run_dir, tmp_path):
    result = court(run_dir, LLMClient(get_settings(offline=True), log=lambda _: None), tmp_path, seed="threshold")
    assert result.passed
    assert [(a["mode"], a["source"]) for a in result.attempts] == [("replay", "llm-cache")]
    assert result.attempts[0]["provenance"]["provider"] == "claude-code"
