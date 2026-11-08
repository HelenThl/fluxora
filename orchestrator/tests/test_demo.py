"""`fluxora demo` end to end, offline from committed artefacts (needs the .NET 8 SDK; port 5091)."""

import json
import re
import shutil

import pytest
from typer.testing import CliRunner

from orchestrator.cli import app

from .conftest import ROOT

pytestmark = pytest.mark.skipif(shutil.which("dotnet") is None, reason="needs the .NET 8 SDK")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    runs_dir = tmp_path_factory.mktemp("runs")
    result = CliRunner().invoke(app, ["demo", "--offline", "--port", "5091", "--runs-dir", str(runs_dir)])
    run_id = re.search(r"DEMO \w+: run (\S+)\.", result.output).group(1)
    return result, runs_dir / run_id


def test_demo_goes_green_then_red_then_green(demo):
    result, _ = demo
    assert result.exit_code == 0, result.output
    out = result.output
    assert "VERDICT: PASS  32/32 cases, 11/11 rules" in out  # clean code
    assert "INITIAL VERDICT: FAIL" in out and "R09-02  status: expected \"Approved\", got \"Pending approval\"" in out
    assert "FINAL VERDICT: PASS" in out
    assert "30/30 are byte-identical to the committed generated/ code" in out


def test_demo_labels_every_stage_honestly(demo):
    result, run_dir = demo
    out = result.output
    assert "Human gate AUTO-APPROVED" in out
    assert "live LLM" not in out.split("MEASURED TIMINGS")[1]  # offline: nothing may claim to be live
    for stage, mode in [
        ("Transform: extract", "cached LLM"),
        ("Transform: approval gate", "auto-approved, no human"),
        ("Rebuild: generate", "cached LLM"),
        ("Verify: judge clean code", "no LLM"),
        ("Verify: seeded defect + repair", "repair: cached LLM"),
        ("Total", ""),
    ]:
        assert re.search(rf"^{re.escape(stage)}\s+\d+\.\d\d\s+{re.escape(mode)}", out, re.M), stage

    evidence = (run_dir / "evidence.md").read_text(encoding="utf-8")
    assert "| Rebuild: generate |" in evidence and "| Total |" in evidence and "cached LLM" in evidence


def test_demo_leaves_committed_code_and_cases_alone(demo):
    _, run_dir = demo
    assert (run_dir / "generated" / "manifest.json").is_file()
    assert json.loads((run_dir / "parity-clean.json").read_text(encoding="utf-8"))["summary"]["result"] == "PASS"
    repairs = json.loads((run_dir / "repairs.json").read_text(encoding="utf-8"))
    assert [(a["mode"], a["source"], a["outcome"]) for a in repairs["attempts"]] == [("replay", "llm-cache", "fixed")]
    committed = (ROOT / "generated" / "api" / "Rules" / "R09.cs").read_text(encoding="utf-8")
    assert "> 5000m" in committed and ">= 5000m" not in committed
