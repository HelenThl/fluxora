"""The rule register on disk: runs/<run-id>/rules.json, plus the human approval gate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

RULES_FILE = "rules.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_run(runs_dir: Path, register: dict) -> tuple[str, Path]:
    """Write a register into a fresh, timestamp-named run folder. Returns (run_id, path)."""
    base = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id, n = base, 1
    while (runs_dir / run_id).exists():
        n += 1
        run_id = f"{base}-{n}"
    path = runs_dir / run_id / RULES_FILE
    path.parent.mkdir(parents=True)
    save(path, {"runId": run_id, "createdAt": now_iso(), **register})
    return run_id, path


def rules_path(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / run_id / RULES_FILE


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def approve(data: dict, *, approve_all: bool, reject: list[str]) -> list[dict]:
    """Record decisions: rejected IDs become "rejected"; with approve_all, every other rule becomes
    "approved". Each decision is appended to data["approvals"] with an ISO timestamp."""
    ids = [r["id"] for r in data["rules"]]
    unknown = [r for r in reject if r not in ids]
    if unknown:
        raise ValueError(f"Unknown rule ID(s): {', '.join(unknown)}. The register has {ids[0]}..{ids[-1]}.")
    if not approve_all and not reject:
        raise ValueError("Nothing to do: pass --all, --reject, or both.")

    at = now_iso()
    decisions = []
    for rule in data["rules"]:
        if rule["id"] in reject:
            decision = "rejected"
        elif approve_all:
            decision = "approved"
        else:
            continue
        rule["status"] = decision
        decisions.append({"ruleId": rule["id"], "decision": decision, "at": at})
    data.setdefault("approvals", []).extend(decisions)
    return decisions
