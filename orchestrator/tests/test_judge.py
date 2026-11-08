"""Parity Court against the real generated API (needs the .NET 8 SDK). Uses port 5091, not 5080."""

import hashlib
import json
import shutil

import pytest
from typer.testing import CliRunner

from orchestrator import register
from orchestrator.cli import app
from orchestrator.judge import JudgeError, judge, port_in_use

from .conftest import FIXTURE, ROOT

pytestmark = pytest.mark.skipif(shutil.which("dotnet") is None, reason="needs the .NET 8 SDK")

PORT = 5091
RUN_ID = "20261108-143433"
COMMITTED_RUN = ROOT / "runs" / RUN_ID / "rules.json"
API_DIR = ROOT / "generated" / "api"


def snapshot() -> dict[str, str]:
    """Hashes of everything the judge must never change."""
    paths = [COMMITTED_RUN, FIXTURE / "reference-cases.json", *sorted((API_DIR / "tests").glob("*.cs*"))]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def api_copy(tmp_path, rule_id: str, old: str, new: str):
    """A copy of generated/api with one rule file hand-edited."""
    copy = tmp_path / "api"
    shutil.copytree(API_DIR, copy, ignore=shutil.ignore_patterns("bin", "obj", "tests"))
    rule_file = copy / "Rules" / f"{rule_id}.cs"
    source = rule_file.read_text(encoding="utf-8")
    assert old in source
    rule_file.write_text(source.replace(old, new), encoding="utf-8")
    return copy


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    before = snapshot()
    verdict = judge(register.load(COMMITTED_RUN), port=PORT, work_dir=tmp_path_factory.mktemp("work"), log=lambda _: None)
    return verdict, before, snapshot()


def test_clean_generated_app_is_all_green(clean):
    verdict, _, _ = clean
    summary = verdict.parity["summary"]
    assert verdict.passed and summary["result"] == "PASS"
    assert summary["cases"] == {"passed": 32, "failed": 0, "total": 32}
    assert summary["rules"] == {"passed": 11, "failed": 0, "total": 11}
    assert all(r["oracle"] == "powerfx-engine" for r in verdict.parity["rules"])
    assert verdict.parity["referenceCases"]["unchanged"] is True


def test_judge_changes_none_of_its_inputs(clean):
    _, before, after = clean
    assert before == after


def test_api_is_not_left_running():
    assert not port_in_use(PORT)


def test_broken_rule_is_named_with_its_case(tmp_path):
    broken = api_copy(tmp_path, "R09", "> 5000m", ">= 5000m")
    verdict = judge(register.load(COMMITTED_RUN), api_dir=broken, port=PORT, work_dir=tmp_path / "work", log=lambda _: None)

    assert not verdict.passed
    failed = [c for c in verdict.parity["cases"] if not c["pass"]]
    assert [c["id"] for c in failed] == ["R09-02"]
    assert failed[0]["implicatedRules"] == ["R09"]
    assert failed[0]["diff"] == {"status": {"expected": "Approved", "actual": "Pending approval"}}

    status = {r["id"]: r["status"] for r in verdict.parity["rules"]}
    assert status["R09"] == "FAIL"
    assert all(s == "PASS" for rule_id, s in status.items() if rule_id != "R09")
    assert not port_in_use(PORT)


def test_build_failure_is_reported_and_nothing_keeps_running(tmp_path):
    broken = api_copy(tmp_path, "R04", "return incidentDate", "retrun incidentDate")
    with pytest.raises(JudgeError, match=r"dotnet build failed[\s\S]*R04\.cs"):
        judge(register.load(COMMITTED_RUN), api_dir=broken, port=PORT, work_dir=tmp_path / "work", log=lambda _: None)
    assert not port_in_use(PORT)


def test_missing_dotnet_gives_a_clear_error_not_a_traceback(tmp_path, monkeypatch):
    import orchestrator.judge as judge_module

    def no_dotnet(*args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(judge_module.subprocess, "run", no_dotnet)
    with pytest.raises(JudgeError, match=r"\.NET 8 SDK was not found"):
        judge(register.load(COMMITTED_RUN), port=PORT, work_dir=tmp_path / "work", log=lambda _: None)


def test_cli_writes_parity_and_exits_zero_when_green(tmp_path):
    runs_dir = tmp_path / "runs"
    (runs_dir / RUN_ID).mkdir(parents=True)
    shutil.copy(COMMITTED_RUN, runs_dir / RUN_ID / "rules.json")

    result = CliRunner().invoke(app, ["judge", RUN_ID, "--port", str(PORT), "--runs-dir", str(runs_dir)])
    assert result.exit_code == 0, result.output
    assert "VERDICT: PASS" in result.output
    parity = json.loads((runs_dir / RUN_ID / "parity.json").read_text(encoding="utf-8"))
    assert parity["summary"]["result"] == "PASS"
    assert len(parity["cases"]) == 32
    assert not port_in_use(PORT)
