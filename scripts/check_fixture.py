"""Check the claim-triage fixture is complete enough to judge against (M0).

Standard library only. Exits non-zero if any check fails.

    python scripts/check_fixture.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "claim-triage"
FIXTURE_FILES = ["app.pa.yaml", "flow.json", "dataverse-schema.json", "reference-cases.json"]
JSON_FILES = ["flow.json", "dataverse-schema.json", "reference-cases.json"]

RULE_IDS = [f"R{n:02d}" for n in range(1, 12)]
VALIDATION_RULES = {"R01", "R02", "R03", "R08"}
ORACLES = {"manual", "powerfx-engine"}
MIN_CASES_PER_RULE = 2

CASE_FIELDS = ["id", "ruleIds", "description", "inputs", "expected", "oracle"]
INPUT_FIELDS = [
    "claimId", "policyNumber", "claimType", "policyStartDate", "incidentDate",
    "reportedDate", "claimAmount", "hasReceipt", "status", "today",
]
EXPECTED_FIELDS = ["errors", "excess", "payable", "lateReport", "status"]
MONEY_FIELDS = [("inputs", "claimAmount"), ("expected", "excess"), ("expected", "payable")]

PENNY = Decimal("0.01")

problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def as_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def is_money(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, Decimal) and value == value.quantize(PENNY)


def check_files() -> dict[str, object]:
    print("Files")
    loaded: dict[str, object] = {}
    for name in FIXTURE_FILES:
        if (FIXTURE / name).is_file():
            ok(f"{name} exists")
        else:
            fail(f"{name} is missing")
    for name in JSON_FILES:
        path = FIXTURE / name
        if not path.is_file():
            continue
        try:
            loaded[name] = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
            ok(f"{name} parses")
        except json.JSONDecodeError as exc:
            fail(f"{name} does not parse: {exc}")
    return loaded


def check_app_formulas() -> None:
    """R01-R08 must appear in app.pa.yaml exactly as written in the CLAUDE.md rule table."""
    print("App formulas vs CLAUDE.md")
    app = FIXTURE / "app.pa.yaml"
    brief = ROOT / "CLAUDE.md"
    if not app.is_file() or not brief.is_file():
        fail("need both app.pa.yaml and CLAUDE.md to compare formulas")
        return
    app_text = app.read_text(encoding="utf-8")
    row = re.compile(r"^\| (R\d\d) \| App \| `(.+?)` \|")
    formulas = {}
    for line in brief.read_text(encoding="utf-8").splitlines():
        m = row.match(line)
        if m:
            formulas[m.group(1)] = m.group(2).replace("\\|", "|")
    expected_app_rules = [f"R{n:02d}" for n in range(1, 9)]
    if sorted(formulas) != expected_app_rules:
        fail(f"CLAUDE.md rule table: expected App rules R01-R08, found {sorted(formulas)}")
    for rule_id, formula in sorted(formulas.items()):
        if formula in app_text:
            ok(f"{rule_id} formula present")
        else:
            fail(f"{rule_id} formula not found verbatim in app.pa.yaml: {formula}")

    notify_count = app_text.count("Notify(")
    if notify_count == 1:
        ok("unsupported construct: one Notify(...) call in app.pa.yaml")
    else:
        fail(f"expected exactly one Notify(...) call in app.pa.yaml, found {notify_count}")


def check_flow(flow: object) -> None:
    print("Flow")
    text = json.dumps(flow)
    for name in ["Condition_Amount", "Condition_LateReport", "Set_Status_Approved"]:
        if f'"{name}"' in text:
            ok(f"{name} present")
        else:
            fail(f"{name} missing from flow.json")
    if text.count('"Send_an_email"') == 1:
        ok("unsupported construct: one Send_an_email action in flow.json")
    else:
        fail("expected exactly one Send_an_email action in flow.json")


def check_precedence(meta: dict) -> None:
    print("Precedence")
    precedence = meta.get("precedence")
    if not isinstance(precedence, list) or not precedence:
        fail("meta.precedence is missing or empty")
        return
    listed = [r for step in precedence for r in step.get("ruleIds", [])]
    for_status = [r for r in RULE_IDS if r not in {"R05", "R06"}]  # R05/R06 compute values, not status
    if sorted(listed) == sorted(for_status):
        ok(f"meta.precedence covers {', '.join(for_status)} once each")
    else:
        fail(f"meta.precedence should list {for_status} once each, found {listed}")


def check_cases(cases: list) -> None:
    print("Cases")
    seen_ids: set[str] = set()
    for i, case in enumerate(cases):
        label = case.get("id", f"#{i}") if isinstance(case, dict) else f"#{i}"
        if not isinstance(case, dict):
            fail(f"case {label} is not an object")
            continue
        missing = [f for f in CASE_FIELDS if f not in case]
        if missing:
            fail(f"case {label} missing fields: {missing}")
            continue
        if case["id"] in seen_ids:
            fail(f"duplicate case id {case['id']}")
        seen_ids.add(case["id"])

        missing_in = [f for f in INPUT_FIELDS if f not in case["inputs"]]
        if missing_in:
            fail(f"case {label} inputs missing: {missing_in}")
        missing_ex = [f for f in EXPECTED_FIELDS if f not in case["expected"]]
        if missing_ex:
            fail(f"case {label} expected missing: {missing_ex}")
        if missing_in or missing_ex:
            continue

        bad_rules = [r for r in case["ruleIds"] if r not in RULE_IDS]
        if bad_rules or not case["ruleIds"]:
            fail(f"case {label} has bad ruleIds: {case['ruleIds']}")
        if case["oracle"] not in ORACLES:
            fail(f"case {label} oracle must be one of {sorted(ORACLES)}")

        for section, field in MONEY_FIELDS:
            value = case[section][field]
            if value is not None and not is_money(value):
                fail(f"case {label} {section}.{field}={value} is not a 2dp decimal")

        for field in ["policyStartDate", "incidentDate", "reportedDate", "today"]:
            if as_date(case["inputs"][field]) is None:
                fail(f"case {label} inputs.{field} is not an ISO date")

        exp = case["expected"]
        if not isinstance(exp["errors"], list):
            fail(f"case {label} expected.errors must be a list")
        elif exp["errors"]:
            if any(e not in VALIDATION_RULES for e in exp["errors"]):
                fail(f"case {label} errors may only hold R01, R02, R03, R08")
            if exp["errors"] != sorted(exp["errors"]):
                fail(f"case {label} errors must be in rule order")
            if any(exp[f] is not None for f in ["excess", "payable", "lateReport", "status"]):
                fail(f"case {label} has errors, so excess/payable/lateReport/status must be null")
        elif any(exp[f] is None for f in ["excess", "payable", "lateReport", "status"]):
            fail(f"case {label} has no errors, so excess/payable/lateReport/status must be set")
    ok(f"{len(cases)} cases checked for required fields and shape")


def check_coverage(cases: list) -> None:
    print("Rule coverage (cases per rule)")
    counts = {r: 0 for r in RULE_IDS}
    for case in cases:
        for r in set(case.get("ruleIds", [])):
            if r in counts:
                counts[r] += 1
    for r in RULE_IDS:
        if counts[r] >= MIN_CASES_PER_RULE:
            ok(f"{r}: {counts[r]}")
        else:
            fail(f"{r}: {counts[r]} case(s), need at least {MIN_CASES_PER_RULE}")


def check_boundaries(cases: list) -> None:
    print("Boundaries")
    valid = [c for c in cases if isinstance(c, dict) and "inputs" in c and "expected" in c]

    def amount(c):
        return c["inputs"].get("claimAmount")

    def days_late(c):
        inc, rep = as_date(c["inputs"].get("incidentDate")), as_date(c["inputs"].get("reportedDate"))
        return (rep - inc).days if inc and rep else None

    def travel(c, amt, receipt):
        i = c["inputs"]
        return i.get("claimType") == "Travel" and amount(c) == Decimal(amt) and i.get("hasReceipt") is receipt

    def incident_vs_today(c, offset):
        inc, today = as_date(c["inputs"].get("incidentDate")), as_date(c["inputs"].get("today"))
        return bool(inc and today and inc == today + timedelta(days=offset))

    def vs_excess(c, delta):
        excess = c["expected"].get("excess")
        return excess is not None and amount(c) is not None and amount(c) == excess + delta

    boundaries = {
        "amount 5000": lambda c: amount(c) == Decimal("5000"),
        "amount 5000.01": lambda c: amount(c) == Decimal("5000.01"),
        "amount 4999.99": lambda c: amount(c) == Decimal("4999.99"),
        "reported day 30": lambda c: days_late(c) == 30,
        "reported day 31": lambda c: days_late(c) == 31,
        "amount equal to excess": lambda c: vs_excess(c, Decimal("0")),
        "amount one penny above excess": lambda c: vs_excess(c, PENNY),
        "Travel 2000 without receipt": lambda c: travel(c, "2000", False),
        "Travel 2000 with receipt": lambda c: travel(c, "2000", True),
        "Travel 2000.01 without receipt": lambda c: travel(c, "2000.01", False),
        "Travel 2000.01 with receipt": lambda c: travel(c, "2000.01", True),
        "IncidentDate equal to PolicyStartDate": lambda c: c["inputs"].get("incidentDate") == c["inputs"].get("policyStartDate"),
        "IncidentDate equal to today": lambda c: incident_vs_today(c, 0),
        "IncidentDate one day after today": lambda c: incident_vs_today(c, 1),
    }
    for name, test in boundaries.items():
        hits = [c["id"] for c in valid if test(c)]
        if hits:
            ok(f"{name}: {', '.join(hits)}")
        else:
            fail(f"{name}: no case")


def main() -> int:
    print(f"Checking {FIXTURE.relative_to(ROOT)}\n")
    loaded = check_files()
    check_app_formulas()
    if "flow.json" in loaded:
        check_flow(loaded["flow.json"])
    ref = loaded.get("reference-cases.json")
    if isinstance(ref, dict):
        check_precedence(ref.get("meta", {}))
        cases = ref.get("cases", [])
        check_cases(cases)
        check_coverage(cases)
        check_boundaries(cases)
    print()
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        return 1
    print("OK: fixture complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
