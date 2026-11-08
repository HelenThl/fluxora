import json
from datetime import datetime

import pytest
from typer.testing import CliRunner

from orchestrator import register
from orchestrator.cli import app
from orchestrator.extract import build_register

from .conftest import FIXTURE


@pytest.fixture
def run(tmp_path, live_client):
    runs_dir = tmp_path / "runs"
    run_id, path = register.new_run(runs_dir, build_register(FIXTURE, live_client).register)
    return runs_dir, run_id, path


def invoke(runs_dir, *args):
    return CliRunner().invoke(app, ["approve", *args, "--runs-dir", str(runs_dir)])


def test_approve_all_timestamps_every_rule(run):
    runs_dir, run_id, path = run
    result = invoke(runs_dir, run_id, "--all")
    assert result.exit_code == 0, result.output

    data = register.load(path)
    assert all(r["status"] == "approved" for r in data["rules"])
    assert [a["ruleId"] for a in data["approvals"]] == [r["id"] for r in data["rules"]]
    for approval in data["approvals"]:
        assert approval["decision"] == "approved"
        assert approval["at"].endswith("Z")
        datetime.fromisoformat(approval["at"].replace("Z", "+00:00"))


def test_reject_overrides_all(run):
    runs_dir, run_id, path = run
    result = invoke(runs_dir, run_id, "--all", "--reject", "R05,r06")
    assert result.exit_code == 0, result.output

    status = {r["id"]: r["status"] for r in register.load(path)["rules"]}
    assert status["R05"] == status["R06"] == "rejected"
    assert all(s == "approved" for rid, s in status.items() if rid not in ("R05", "R06"))


def test_unknown_rule_id_fails_and_changes_nothing(run):
    runs_dir, run_id, path = run
    before = path.read_text(encoding="utf-8")
    result = invoke(runs_dir, run_id, "--reject", "R99")
    assert result.exit_code != 0
    assert "R99" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_no_decision_flags_fails(run):
    runs_dir, run_id, _ = run
    assert invoke(runs_dir, run_id).exit_code != 0


def test_unknown_run_fails(tmp_path):
    assert invoke(tmp_path, "20000101-000000", "--all").exit_code != 0
