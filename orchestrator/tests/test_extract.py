import json
import re
import shutil

import pytest
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.extract import RULE_KEYS, ExtractError, build_register
from orchestrator.llm import LLMClient, Settings, get_settings

from .conftest import FIXTURE, ROOT

RULE_IDS = [f"R{n:02d}" for n in range(1, 12)]


def brief_app_formulas() -> dict[str, str]:
    """R01-R08 exactly as written in the CLAUDE.md rule table."""
    row = re.compile(r"^\| (R\d\d) \| App \| `(.+?)` \|")
    formulas = {}
    for line in (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines():
        m = row.match(line)
        if m:
            formulas[m.group(1)] = m.group(2).replace("\\|", "|")
    return formulas


@pytest.fixture
def register(live_client):
    return build_register(FIXTURE, live_client).register


def test_extracts_exactly_r01_to_r11_with_source_refs(register):
    rules = register["rules"]
    assert [r["id"] for r in rules] == RULE_IDS
    for rule in rules:
        assert tuple(rule) == RULE_KEYS
        assert rule["source"]["file"] in ("app.pa.yaml", "flow.json")
        assert rule["source"]["ref"]
        assert rule["formula"]
        assert rule["rule"]
        assert rule["confidence"] in ("high", "medium", "low")
        assert rule["status"] == "pending"


def test_app_formulas_match_the_brief_verbatim(register):
    by_id = {r["id"]: r for r in register["rules"]}
    expected = brief_app_formulas()
    assert sorted(expected) == RULE_IDS[:8]
    for rule_id, formula in expected.items():
        assert by_id[rule_id]["formula"] == formula
        assert by_id[rule_id]["source"]["file"] == "app.pa.yaml"


def test_flow_rules_are_read_from_flow_json(register):
    by_id = {r["id"]: r for r in register["rules"]}
    assert by_id["R09"]["formula"] == "ClaimAmount > 5000"
    assert by_id["R09"]["source"]["ref"] == "actions.Condition_LateReport.else.actions.Condition_Amount"
    assert by_id["R10"]["formula"] == "div(sub(ticks(ReportedDate), ticks(IncidentDate)), 864000000000) > 30"
    assert by_id["R11"]["formula"] == "otherwise"


def test_outputs_and_inputs_are_derived_from_the_fixture(register):
    by_id = {r["id"]: r for r in register["rules"]}
    assert [by_id[i]["output"] for i in ("R01", "R02", "R03", "R08")] == ["Errors"] * 4
    assert [by_id[i]["output"] for i in ("R04", "R07", "R09", "R11")] == ["Status"] * 4
    assert by_id["R05"]["output"] == "Excess"
    assert by_id["R06"]["output"] == "Payable"
    assert by_id["R10"]["output"] == "LateReport, Status"
    assert by_id["R06"]["inputs"] == ["ClaimAmount", "Excess"]
    assert by_id["R09"]["inputs"] == ["ClaimAmount"]


def test_unsupported_lists_exactly_the_two_known_constructs(register):
    unsupported = register["unsupported"]
    assert len(unsupported) == 2
    by_construct = {u["construct"]: u for u in unsupported}
    assert set(by_construct) == {"Notify(...)", "Send_an_email"}
    assert by_construct["Notify(...)"]["file"] == "app.pa.yaml"
    assert by_construct["Notify(...)"]["ref"] == "ClaimScreen.btnSubmit.OnSelect"
    assert by_construct["Send_an_email"]["file"] == "flow.json"
    assert by_construct["Send_an_email"]["ref"].endswith("Condition_Amount.actions.Send_an_email")
    assert all(u["reason"] for u in unsupported)


def test_precedence_matches_the_fixture(register):
    meta = json.loads((FIXTURE / "reference-cases.json").read_text(encoding="utf-8"))["meta"]
    assert register["precedence"] == [step["ruleIds"] for step in meta["precedence"]]


def test_missing_pinned_rule_fails_loudly(tmp_path, live_client):
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    ids_file = fixture / "rule-ids.json"
    data = json.loads(ids_file.read_text(encoding="utf-8"))
    data["ids"]["app.pa.yaml#App.Formulas.DoesNotExist"] = "R99"
    ids_file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ExtractError, match="DoesNotExist"):
        build_register(fixture, live_client)


def test_unpinned_rule_gets_next_id_with_warning(tmp_path, live_client):
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    ids_file = fixture / "rule-ids.json"
    data = json.loads(ids_file.read_text(encoding="utf-8"))
    del data["ids"]["app.pa.yaml#App.Formulas.Excess"]
    ids_file.write_text(json.dumps(data), encoding="utf-8")
    result = build_register(fixture, live_client)
    ids = [r["id"] for r in result.register["rules"]]
    assert "R05" not in ids and "R12" in ids
    assert any("Excess" in w and "R12" in w for w in result.warnings)


def test_offline_with_warm_cache_gives_identical_register(tmp_path, fake_transport, live_client):
    live = build_register(FIXTURE, live_client).register
    assert fake_transport.calls == 11

    # Offline, no model configured: the client must find every answer in the warm cache.
    offline_settings = Settings(provider=None, api_key=None, model=None, base_url=None, offline=True)
    offline_client = LLMClient(offline_settings, cache_dir=tmp_path / "cache", log=lambda _: None)
    offline = build_register(FIXTURE, offline_client).register

    assert offline == live
    assert fake_transport.calls == 11
    assert offline_client.cache_hits == 11 and offline_client.live_calls == 0


def test_committed_cache_serves_the_demo_offline():
    """Guards the demo: the committed cache must answer every rule prompt with no key set."""
    client = LLMClient(get_settings(offline=True), log=lambda _: None)
    result = build_register(FIXTURE, client)
    assert [r["id"] for r in result.register["rules"]] == RULE_IDS
    assert client.live_calls == 0


def test_cli_extract_offline_writes_a_run(tmp_path):
    result = CliRunner().invoke(app, ["extract", str(FIXTURE), "--offline", "--runs-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    run_id = re.search(r"Run ID: (\S+)", result.output).group(1)
    written = json.loads((tmp_path / run_id / "rules.json").read_text(encoding="utf-8"))
    assert written["runId"] == run_id
    assert [r["id"] for r in written["rules"]] == RULE_IDS
    assert written["approvals"] == []
