"""Data migration: Dataverse rows -> Cosmos DB Claim documents, with a reconciliation report.

The mapping comes from dataverse-schema.json (one column -> one document property), and the target
shape is checked against the generated ClaimDocument.cs, so the documents fit the migrated app.

A row that cannot be migrated safely is quarantined with its reasons, never dropped or guessed at.
The run passes only if every source row is accounted for and every migrated document maps back to
its source row exactly.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .register import now_iso

SCHEMA_FILE = "dataverse-schema.json"
RECORDS_FILE = "dataverse-records.json"
DOCUMENTS_FILE = "migrated-claims.json"
REPORT_FILE = "migration.json"
DOCUMENT_CS = Path("api") / "Data" / "ClaimDocument.cs"

# Kept on every document so each one traces back to its Dataverse row. Not part of ClaimDocument.cs
# (Newtonsoft ignores unknown properties when the app reads the document).
SOURCE_PROPERTY = "sourceRecord"
# Cosmos DB does not allow these characters in a document id.
COSMOS_ID_FORBIDDEN = re.compile(r"[/\\?#]")


class MigrationError(Exception):
    pass


@dataclass
class Migration:
    report: dict
    documents: list[dict]


ROOT = Path(__file__).resolve().parent.parent


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target_property(column: dict) -> str:
    return "id" if column.get("isPrimaryName") else _camel(column["field"])


def _document_properties(generated_dir: Path) -> set[str]:
    path = generated_dir / DOCUMENT_CS
    if not path.is_file():
        raise MigrationError(f"No {DOCUMENT_CS.as_posix()} under {generated_dir}. Run `fluxora generate` first.")
    return set(re.findall(r'\[JsonProperty\("([^"]+)"\)\]', path.read_text(encoding="utf-8")))


def _convert(column: dict, raw: object) -> tuple[object, str | None, bool]:
    """One Dataverse value -> (document value, problem or None, defaulted?)."""
    kind, name = column["type"], column["logicalName"]
    if raw is None or raw == "":
        if "default" in column:
            return column["default"], None, True
        if column.get("required"):
            return None, f"{name}: required value is missing", False
        return None, None, False
    if kind == "String":
        if not isinstance(raw, str):
            return None, f"{name}: expected text, got {json.dumps(raw)}", False
        if len(raw) > column.get("maxLength", len(raw)):
            return None, f"{name}: {len(raw)} characters, longer than the column's maxLength {column['maxLength']}", False
        return raw, None, False
    if kind == "Picklist":
        labels = {o["value"]: o["label"] for o in column["options"]}
        if raw not in labels:
            return None, f"{name}: option value {raw} is not in the schema's option set", False
        return labels[raw], None, False
    if kind == "DateTime":
        try:
            return date.fromisoformat(str(raw)).isoformat(), None, False
        except ValueError:
            return None, f"{name}: {json.dumps(raw)} is not a valid date (YYYY-MM-DD)", False
    if kind == "Money":
        try:
            amount = Decimal(str(raw))
        except InvalidOperation:
            return None, f"{name}: {json.dumps(raw)} is not a number", False
        precision = column.get("precision", 2)
        if amount != amount.quantize(Decimal(1).scaleb(-precision)):
            return None, f"{name}: {raw} has more than {precision} decimal places", False
        return amount, None, False
    if kind == "Boolean":
        if not isinstance(raw, bool):
            return None, f"{name}: expected true or false, got {json.dumps(raw)}", False
        return raw, None, False
    raise MigrationError(f"Column {name} has type {kind}, which the migration does not handle.")


def _back_to_source(column: dict, value: object) -> object:
    """Document value -> the Dataverse value it came from (for the round-trip check)."""
    if value is None:
        return None
    if column["type"] == "Picklist":
        return next(o["value"] for o in column["options"] if o["label"] == value)
    if column["type"] == "Money":
        return Decimal(str(value))
    return value


def _source_value(column: dict, row: dict) -> object:
    raw = row.get(column["logicalName"])
    if (raw is None or raw == "") and "default" in column:
        return column["default"]
    if column["type"] == "Money" and raw is not None:
        return Decimal(str(raw))
    return raw


def migrate(fixture_dir: Path, generated_dir: Path) -> Migration:
    """Map every Dataverse row to a Cosmos document or to the quarantine list. Writes nothing."""
    schema_path, records_path = fixture_dir / SCHEMA_FILE, fixture_dir / RECORDS_FILE
    for path in (schema_path, records_path):
        if not path.is_file():
            raise MigrationError(f"Missing {path}")
    source_sha = _sha256(records_path)
    table = json.loads(schema_path.read_text(encoding="utf-8"))["tables"][0]
    columns = table["columns"]
    rows = json.loads(records_path.read_text(encoding="utf-8"), parse_float=Decimal)["value"]
    primary_id = table["primaryIdAttribute"]

    # The documents must fit the migrated app's ClaimDocument.
    known = _document_properties(generated_dir)
    missing = sorted({_target_property(c) for c in columns} - known)
    if missing:
        raise MigrationError(f"ClaimDocument.cs has no property for: {', '.join(missing)}. Regenerate the API.")

    id_column = next(c for c in columns if c.get("isPrimaryName"))
    claim_ids: dict[str, int] = {}
    for row in rows:
        claim_ids[row.get(id_column["logicalName"])] = claim_ids.get(row.get(id_column["logicalName"]), 0) + 1

    documents, quarantined, defaulted = [], [], []
    for index, row in enumerate(rows):
        doc, problems = {}, []
        for column in columns:
            value, problem, was_defaulted = _convert(column, row.get(column["logicalName"]))
            if problem:
                problems.append(problem)
            if was_defaulted:
                defaulted.append({"record": row.get(primary_id), "column": column["logicalName"], "value": value})
            doc[_target_property(column)] = value
        claim_id = row.get(id_column["logicalName"])
        if isinstance(claim_id, str) and COSMOS_ID_FORBIDDEN.search(claim_id):
            problems.append(f"{id_column['logicalName']}: {claim_id!r} has a character Cosmos DB does not allow in an id")
        if claim_id is not None and claim_ids[claim_id] > 1:
            problems.append(
                f"{id_column['logicalName']}: {claim_id} is on {claim_ids[claim_id]} rows; it becomes the Cosmos "
                "document id, so one row would overwrite the other. A person must decide which is correct"
            )
        if problems:
            quarantined.append({"row": index, "record": row.get(primary_id), "claimId": claim_id, "reasons": problems})
            continue
        doc[SOURCE_PROPERTY] = {
            "table": table["logicalName"],
            "id": row.get(primary_id),
            "modifiedOn": row.get("modifiedon"),
        }
        documents.append(doc)

    documents.sort(key=lambda d: d["id"])
    report = {
        "migratedAt": now_iso(),
        "source": {
            "path": _display(records_path),
            "table": table["logicalName"],
            "entitySet": table["entitySetName"],
            "sha256Before": source_sha,
        },
        "target": {
            "store": "Cosmos DB",
            "document": DOCUMENT_CS.as_posix(),
            "id": _target_property(id_column),
            "partitionKey": "/policyNumber",
            "file": DOCUMENTS_FILE,
        },
        "mapping": [
            {"from": c["logicalName"], "to": _target_property(c), "type": c["type"],
             **({"options": {str(o["value"]): o["label"] for o in c["options"]}} if c["type"] == "Picklist" else {})}
            for c in columns
        ],
        "counts": {"read": len(rows), "migrated": len(documents), "quarantined": len(quarantined)},
        "quarantined": quarantined,
        "defaulted": defaulted,
    }
    return Migration(report, documents)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)  # 2-decimal amounts round-trip exactly; reconcile() proves it
    raise TypeError(type(value).__name__)


def reconcile(fixture_dir: Path, documents_path: Path, report: dict) -> dict:
    """Read the written documents back and check them against the source, independently of migrate()."""
    schema = json.loads((fixture_dir / SCHEMA_FILE).read_text(encoding="utf-8"))["tables"][0]
    columns, primary_id = schema["columns"], schema["primaryIdAttribute"]
    rows = json.loads((fixture_dir / RECORDS_FILE).read_text(encoding="utf-8"), parse_float=Decimal)["value"]
    docs = json.loads(documents_path.read_text(encoding="utf-8"), parse_float=Decimal)
    by_record = {row.get(primary_id): row for row in rows}
    quarantined = {q["record"] for q in report["quarantined"]}
    migrated = [d[SOURCE_PROPERTY]["id"] for d in docs]

    checks = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": ok, "detail": detail})

    unaccounted = sorted(set(by_record) - set(migrated) - quarantined)
    twice = sorted(set(migrated) & quarantined) + sorted({m for m in migrated if migrated.count(m) > 1})
    check(
        "Every row accounted for",
        len(rows) == len(docs) + len(quarantined) and not unaccounted and not twice,
        f"{len(rows)} read = {len(docs)} migrated + {len(quarantined)} quarantined"
        + (f"; unaccounted {unaccounted}" if unaccounted else "") + (f"; counted twice {twice}" if twice else ""),
    )
    ids = [d["id"] for d in docs]
    check("Document ids unique", len(ids) == len(set(ids)), f"{len(set(ids))} distinct ids for {len(ids)} documents")

    mismatches = []
    for doc in docs:
        row = by_record.get(doc[SOURCE_PROPERTY]["id"])
        if row is None:
            mismatches.append(f"{doc['id']}: source row {doc[SOURCE_PROPERTY]['id']} not found")
            continue
        for column in columns:
            got = _back_to_source(column, doc.get(_target_property(column)))
            want = _source_value(column, row)
            if got != want:
                mismatches.append(f"{doc['id']}.{_target_property(column)}: source {want!r}, document {got!r}")
    check(
        "Round trip: each document maps back to its row",
        not mismatches,
        f"{len(docs) * len(columns)} values compared, {len(mismatches)} differ" + (f": {mismatches[:5]}" if mismatches else ""),
    )

    migrated_rows = [by_record[m] for m in migrated if m in by_record]
    money = next(c for c in columns if c["type"] == "Money")
    source_total = sum((_source_value(money, r) for r in migrated_rows), Decimal(0))
    target_total = sum((Decimal(str(d[_target_property(money)])) for d in docs), Decimal(0))
    check(
        f"Control total: {_target_property(money)}",
        source_total == target_total,
        f"source £{source_total:,.2f}, documents £{target_total:,.2f}",
    )
    for column in (c for c in columns if c["type"] == "Picklist"):
        target_key = _target_property(column)
        labels = {o["value"]: o["label"] for o in column["options"]}
        source_counts: dict[str, int] = {}
        target_counts: dict[str, int] = {}
        for r in migrated_rows:
            key = labels.get(r.get(column["logicalName"]), "(blank)")
            source_counts[key] = source_counts.get(key, 0) + 1
        for d in docs:
            key = d.get(target_key) or "(blank)"
            target_counts[key] = target_counts.get(key, 0) + 1
        check(
            f"Counts by {target_key}",
            source_counts == target_counts,
            ", ".join(f"{k} {v}" for k, v in sorted(target_counts.items())),
        )

    after = _sha256(fixture_dir / RECORDS_FILE)
    check("Source unchanged", after == report["source"]["sha256Before"], f"sha256 {after[:12]}")
    return {"result": "PASS" if all(c["pass"] for c in checks) else "FAIL", "checks": checks}


def run_migration(fixture_dir: Path, generated_dir: Path, run_dir: Path) -> dict:
    """Migrate, write the documents and the report into the run folder, reconcile. Returns the report."""
    migration = migrate(fixture_dir, generated_dir)
    documents_path = run_dir / DOCUMENTS_FILE
    documents_path.write_text(
        json.dumps(migration.documents, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8", newline="\n",
    )
    report = migration.report
    report["source"]["sha256After"] = _sha256(fixture_dir / RECORDS_FILE)
    report["target"]["sha256"] = _sha256(documents_path)
    report["reconciliation"] = reconcile(fixture_dir, documents_path, report)
    report["result"] = report["reconciliation"]["result"]
    (run_dir / REPORT_FILE).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return report
