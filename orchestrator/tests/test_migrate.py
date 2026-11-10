"""Data migration: Dataverse rows -> Cosmos DB documents, quarantine and reconciliation (no .NET needed)."""

import json
import shutil
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from orchestrator import migrate as m
from orchestrator import register
from orchestrator.cli import app

from .conftest import FIXTURE, ROOT

GENERATED = ROOT / "generated"
COMMITTED_RUN = ROOT / "runs" / "20261108-143433"


@pytest.fixture
def report(tmp_path):
    return m.run_migration(FIXTURE, GENERATED, tmp_path), tmp_path


def test_every_row_is_migrated_or_quarantined_and_reconciles(report):
    rep, run_dir = report
    assert rep["counts"] == {"read": 40, "migrated": 33, "quarantined": 7}
    assert rep["result"] == "PASS"
    assert all(c["pass"] for c in rep["reconciliation"]["checks"])
    docs = json.loads((run_dir / m.DOCUMENTS_FILE).read_text(encoding="utf-8"))
    assert len(docs) == 33 and json.loads((run_dir / m.REPORT_FILE).read_text(encoding="utf-8"))["result"] == "PASS"


def test_each_planted_problem_is_quarantined_with_its_reason(report):
    rep, _ = report
    reasons = {(q["claimId"], r) for q in rep["quarantined"] for r in q["reasons"]}
    text = " | ".join(r for _, r in reasons)
    duplicates = [q for q in rep["quarantined"] if any("is on 2 rows" in r for r in q["reasons"])]
    assert len(duplicates) == 2 and len({q["record"] for q in duplicates}) == 2  # both rows, no guessing which is right
    assert "option value 100000007 is not in the schema's option set" in text
    assert "fx_claimamount: required value is missing" in text
    assert "1234.567 has more than 2 decimal places" in text
    assert "longer than the column's maxLength 20" in text
    assert '"2026-02-30" is not a valid date' in text


def test_documents_fit_the_generated_claim_document(report):
    _, run_dir = report
    cs = (GENERATED / "api" / "Data" / "ClaimDocument.cs").read_text(encoding="utf-8")
    for doc in json.loads((run_dir / m.DOCUMENTS_FILE).read_text(encoding="utf-8")):
        for key in doc:
            assert key == m.SOURCE_PROPERTY or f'[JsonProperty("{key}")]' in cs, key
        assert doc["claimType"] in {"Motor", "Home", "Travel"}  # option values became labels
        assert doc[m.SOURCE_PROPERTY]["table"] == "fx_claim"


def test_empty_optional_values_are_defaulted_and_reported(report):
    rep, run_dir = report
    assert [(d["column"], d["value"]) for d in rep["defaulted"]] == [("fx_hasreceipt", False)]
    docs = {d["id"]: d for d in json.loads((run_dir / m.DOCUMENTS_FILE).read_text(encoding="utf-8"))}
    assert sum(d["status"] is None for d in docs.values()) == 1  # optional status left blank, not invented


def test_amounts_survive_exactly(report):
    _, run_dir = report
    docs = json.loads((run_dir / m.DOCUMENTS_FILE).read_text(encoding="utf-8"), parse_float=Decimal)
    by_id = {d["id"]: d for d in docs}
    assert by_id["CLM-900017"]["claimAmount"] == Decimal("5000.00")
    assert by_id["CLM-900018"]["claimAmount"] == Decimal("5000.01")


def test_reconciliation_catches_a_tampered_document(report):
    rep, run_dir = report
    path = run_dir / m.DOCUMENTS_FILE
    docs = json.loads(path.read_text(encoding="utf-8"))
    docs[0]["claimAmount"] += 1
    docs.pop()
    path.write_text(json.dumps(docs), encoding="utf-8")
    result = m.reconcile(FIXTURE, path, rep)
    failed = {c["check"] for c in result["checks"] if not c["pass"]}
    assert result["result"] == "FAIL"
    assert {"Every row accounted for", "Round trip: each document maps back to its row", "Control total: claimAmount"} <= failed


def test_missing_document_property_stops_the_migration(tmp_path):
    api = tmp_path / "api" / "Data"
    api.mkdir(parents=True)
    source = (GENERATED / "api" / "Data" / "ClaimDocument.cs").read_text(encoding="utf-8")
    (api / "ClaimDocument.cs").write_text(source.replace('[JsonProperty("hasReceipt")]', ""), encoding="utf-8")
    with pytest.raises(m.MigrationError, match="hasReceipt"):
        m.migrate(FIXTURE, tmp_path)


def test_source_records_are_never_modified(report):
    rep, _ = report
    assert rep["source"]["sha256Before"] == rep["source"]["sha256After"]


def test_cli_migrate_writes_the_report_and_evidence_shows_it(tmp_path):
    runs_dir = tmp_path / "runs"
    shutil.copytree(COMMITTED_RUN, runs_dir / COMMITTED_RUN.name)
    run = runs_dir / COMMITTED_RUN.name
    for name in (m.REPORT_FILE, m.DOCUMENTS_FILE):
        (run / name).unlink(missing_ok=True)
    result = CliRunner().invoke(app, ["migrate", COMMITTED_RUN.name, "--runs-dir", str(runs_dir)])
    assert result.exit_code == 0, result.output
    assert "Read 40 rows from fx_claim: 33 migrated, 7 quarantined." in result.output
    assert "MIGRATION: PASS" in result.output
    assert register.load(run / register.RULES_FILE)  # register untouched and readable

    result = CliRunner().invoke(app, ["evidence", COMMITTED_RUN.name, "--runs-dir", str(runs_dir)])
    assert result.exit_code == 0, result.output
    evidence = (run / "evidence.md").read_text(encoding="utf-8")
    assert "## Data migration" in evidence and "**Data migration:** **PASS**" in evidence
    assert "| Every row accounted for | PASS | 40 read = 33 migrated + 7 quarantined |" in evidence
