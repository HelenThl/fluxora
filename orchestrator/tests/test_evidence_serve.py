import http.client
import json
import shutil
import threading
import urllib.error
import urllib.request

import pytest
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.evidence import load_run, render_markdown, write_evidence
from orchestrator.serve import make_server

from .conftest import ROOT

RUN_ID = "20261108-143433"
COMMITTED_RUN_DIR = ROOT / "runs" / RUN_ID


@pytest.fixture
def run_copy(tmp_path):
    folder = tmp_path / "runs" / RUN_ID
    folder.mkdir(parents=True)
    for name in ("rules.json", "parity.json", "repairs.json"):
        shutil.copy(COMMITTED_RUN_DIR / name, folder / name)
    return folder


# --- evidence -------------------------------------------------------------------------------------


def test_evidence_summary_matches_the_committed_run():
    ev = load_run(COMMITTED_RUN_DIR)["evidence"]
    assert ev["register"] | {"lastDecisionAt": None} == {
        "rules": 11, "approved": 11, "rejected": 0, "pending": 0, "decisions": 11, "lastDecisionAt": None,
    }
    assert ev["oracle"] == {"powerfx-engine": 32}
    assert [u["construct"] for u in ev["unsupported"]] == ["Notify(...)", "Send_an_email"]
    assert ev["parity"]["result"] == "PASS" and ev["parity"]["initial"]["result"] == "FAIL"
    assert ev["repairs"]["fixed"] == ["R09"] and ev["repairs"]["unresolved"] == []
    assert ev["tamperGuard"]["unchanged"] is True
    assert any("synthetic" in note for note in ev["dataNotes"])
    assert any("replay" in note for note in ev["dataNotes"])  # a replayed repair is never presented as live


def test_evidence_markdown_has_every_section_and_escapes_pipes():
    md = render_markdown(load_run(COMMITTED_RUN_DIR))
    for heading in ("## Summary", "## Rule register", "## Parity Court", "## Repair log", "## Unsupported items", "## Oracle coverage", "## Timings", "## Data notes"):
        assert heading in md
    assert "`IsBlank(ClaimAmount) \\|\\| ClaimAmount <= 0`" in md  # R01's || must not break the table
    assert "```diff" in md and "+        return (claimAmount ?? 0m) > 5000m;" in md
    assert "R09-02 (rules R09): status expected `\"Approved\"`, got `\"Pending approval\"`" in md


def test_cli_evidence_writes_the_file(run_copy):
    result = CliRunner().invoke(app, ["evidence", RUN_ID, "--runs-dir", str(run_copy.parent)])
    assert result.exit_code == 0, result.output
    assert (run_copy / "evidence.md").read_text(encoding="utf-8").startswith(f"# Fluxora evidence: run {RUN_ID}")


def test_demo_timings_survive_a_later_evidence_run(run_copy):
    stages = [{"stage": "Verify: judge clean code", "seconds": 4.41, "mode": "no LLM"},
              {"stage": "Total", "seconds": 4.41, "mode": ""}]
    write_evidence(run_copy, ROOT, demo_timings=stages)
    assert json.loads((run_copy / "timings.json").read_text(encoding="utf-8")) == {"stages": stages}

    result = CliRunner().invoke(app, ["evidence", RUN_ID, "--runs-dir", str(run_copy.parent)])
    assert result.exit_code == 0, result.output
    text = (run_copy / "evidence.md").read_text(encoding="utf-8")
    assert "| Verify: judge clean code | 4.41 | no LLM |" in text
    assert "| Total | 4.41 |  |" in text


# --- serve ----------------------------------------------------------------------------------------


@pytest.fixture
def server(run_copy, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>dashboard</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
    httpd = make_server(run_copy, port=0, dist=dist)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", httpd.server_address[1], run_copy
    finally:
        httpd.shutdown()
        httpd.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers.get("Content-Type"), response.read().decode("utf-8")


def post(url, body, origin=None):
    headers = {"Content-Type": "application/json"} | ({"Origin": origin} if origin else {})
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_run_api_and_static_files(server):
    base, _, _ = server
    status, _, body = get(f"{base}/api/run")
    run = json.loads(body)
    assert status == 200 and run["runId"] == RUN_ID and run["evidence"]["register"]["rules"] == 11
    assert get(f"{base}/")[2].startswith("<!doctype html>")
    assert get(f"{base}/verify")[2].startswith("<!doctype html>")  # single-page fallback
    status, content_type, _ = get(f"{base}/assets/app.js")
    assert status == 200 and content_type.startswith("text/javascript")
    status, _, body = get(f"{base}/runs/{RUN_ID}/parity.json")
    assert status == 200 and json.loads(body)["summary"]["result"] == "PASS"


@pytest.mark.parametrize("path", ["/../pyproject.toml", "/runs/x/rules.json", f"/runs/{RUN_ID}/../{RUN_ID}/rules.json", "/api/file?path=../.env"])
def test_nothing_outside_the_allowed_files_is_served(server, path):
    _, port, _ = server
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", path)
    assert connection.getresponse().status in (403, 404)


def test_generated_file_listed_in_manifest_is_served(server):
    base, _, _ = server
    status, _, body = get(f"{base}/api/file?path=api/Rules/R09.cs")
    assert status == 200 and json.loads(body)["content"].startswith("// Rule R09")


def test_approve_endpoint_writes_timestamped_decisions(server):
    base, _, run_dir = server
    status, body = post(f"{base}/api/approve", {"reject": ["R05"]})
    assert status == 200 and body["decisions"][0]["ruleId"] == "R05"
    data = json.loads((run_dir / "rules.json").read_text(encoding="utf-8"))
    assert next(r for r in data["rules"] if r["id"] == "R05")["status"] == "rejected"
    assert data["approvals"][-1]["decision"] == "rejected" and data["approvals"][-1]["at"].endswith("Z")

    status, _ = post(f"{base}/api/approve", {"approve": ["R05"]})
    assert status == 200
    data = json.loads((run_dir / "rules.json").read_text(encoding="utf-8"))
    assert next(r for r in data["rules"] if r["id"] == "R05")["status"] == "approved"


def test_approve_endpoint_refuses_bad_requests(server):
    base, _, run_dir = server
    before = (run_dir / "rules.json").read_text(encoding="utf-8")
    assert post(f"{base}/api/approve", {"approve": ["R99"]})[0] == 400
    assert post(f"{base}/api/approve", {})[0] == 400
    assert post(f"{base}/api/approve", {"all": True}, origin="https://evil.example")[0] == 403
    assert (run_dir / "rules.json").read_text(encoding="utf-8") == before
