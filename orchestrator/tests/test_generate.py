import hashlib
import json

import pytest

from orchestrator import register
from orchestrator.extract import build_register
from orchestrator.generate import GenerateError, generate, write
from orchestrator.llm import LLMClient, Settings, get_settings

from .conftest import FIXTURE, ROOT

RULE_IDS = [f"R{n:02d}" for n in range(1, 12)]
COMMITTED_RUN = ROOT / "runs" / "20261108-143433" / "rules.json"


@pytest.fixture
def approved(live_client):
    data = build_register(FIXTURE, live_client).register
    register.approve(data, approve_all=True, reject=[])
    return data


def tree_hash(folder):
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_one_file_per_rule_with_id_and_sentence(approved, live_client, tmp_path):
    result = generate(approved, live_client)
    write(result, tmp_path)
    for rule in approved["rules"]:
        source = (tmp_path / "api" / "Rules" / f"{rule['id']}.cs").read_text(encoding="utf-8")
        assert source.startswith(f"// Rule {rule['id']}\n")
        assert rule["rule"] in source
        assert f"public static class {rule['id']}" in source
    assert sorted(p.stem for p in (tmp_path / "api" / "Rules").glob("*.cs")) == RULE_IDS


def test_evaluator_follows_the_register_precedence(approved, live_client):
    evaluator = generate(approved, live_client).contents["api/Evaluator.cs"].decode()
    chain = [evaluator.index(f"({rule}.Applies(") for rule in ("R04", "R07", "R10", "R09", "R11")]
    assert chain == sorted(chain)
    assert evaluator.index("R01.Applies(") < evaluator.index("if (errors.Count > 0)") < evaluator.index("R05.Compute(")
    # No business values in the Evaluator: statuses and messages come from the rule classes.
    assert '"Not covered"' not in evaluator and "5000" not in evaluator


def test_rule_constants_come_from_the_fixture(approved, live_client):
    contents = generate(approved, live_client).contents
    assert 'public const string Status = "Not covered";' in contents["api/Rules/R04.cs"].decode()
    assert 'public const string Status = "Manual review";' in contents["api/Rules/R10.cs"].decode()
    assert 'Message = "Amount must be greater than zero";' in contents["api/Rules/R01.cs"].decode()
    assert "DateOnly today" in contents["api/Rules/R03.cs"].decode()


def test_rejected_rule_is_skipped_and_reported(approved, live_client, tmp_path):
    register.approve(approved, approve_all=False, reject=["R09"])
    result = generate(approved, live_client)
    write(result, tmp_path)
    assert result.skipped == [("R09", "rejected")]
    assert not (tmp_path / "api" / "Rules" / "R09.cs").exists()
    assert "R09." not in result.contents["api/Evaluator.cs"].decode()
    manifest = json.loads(result.contents["manifest.json"])
    assert manifest["skipped"] == [{"id": "R09", "status": "rejected"}]


def test_dependency_on_a_skipped_rule_fails_loudly(approved, live_client):
    register.approve(approved, approve_all=False, reject=["R05"])
    with pytest.raises(GenerateError, match="R06 needs Excess from R05"):
        generate(approved, live_client)


def test_pending_rules_are_not_generated(live_client):
    pending = build_register(FIXTURE, live_client).register
    with pytest.raises(GenerateError, match="No approved rules"):
        generate(pending, live_client)


def test_offline_rerun_is_byte_identical(approved, live_client, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write(generate(approved, live_client), first)
    offline = LLMClient(
        Settings(provider=None, api_key=None, model=None, base_url=None, offline=True),
        cache_dir=live_client.cache_dir,
        log=lambda _: None,
    )
    write(generate(approved, offline), second)
    assert offline.live_calls == 0
    assert tree_hash(first) == tree_hash(second)


def test_committed_cache_regenerates_committed_code(tmp_path):
    """Guards the demo: offline, with no key, the committed run and cache reproduce generated/ exactly."""
    client = LLMClient(get_settings(offline=True), log=lambda _: None)
    result = generate(register.load(COMMITTED_RUN), client)
    assert client.live_calls == 0
    for path, data in result.contents.items():
        assert (ROOT / "generated" / path).read_bytes() == data, f"generated/{path} differs from a fresh offline generate"
