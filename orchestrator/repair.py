"""Seeded defects, the bounded repair loop and the tamper guard around a Parity Court run.

Every run works on a copy of generated/api in runs/<run-id>/work/api, so committed code is never
edited. The repair agent may change only Rules/<rule>.cs in that copy, gets at most three attempts per
rule, and every attempt is logged in repairs.json with an honest mode: "live" for a real API call made
in this run, "replay" for a cached LLM response or a recorded patch.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

from .judge import CASES_FILE, DEFAULT_API_DIR, DEFAULT_PORT, JudgeError, Verdict, judge
from .llm import LLMClient, LLMError
from .register import now_iso

ROOT = Path(__file__).resolve().parent.parent
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "repair_rule.md"
RECORDED_DIR = Path(__file__).resolve().parent / "recorded"
MAX_ATTEMPTS = 3

DEFECTS = {
    "threshold": {
        "rule": "R09",
        "from": ">",
        "to": ">=",
        "description": "Rule R09's comparison changed from > to >=, so a claim of exactly £5,000 goes to a manager.",
    }
}
# A comparison '>' that is not part of '=>', '>=', '>>', '->' or '<>'.
GREATER_THAN = re.compile(r"(?<![=<>!\-])>(?![=>])")


class RepairError(RuntimeError):
    pass


@dataclass
class Patch:
    mode: str  # "live" | "replay"
    source: str  # "llm-api" | "llm-cache" | "recorded-patch"
    provenance: dict
    reply: str | None = None  # raw LLM reply, parsed by validate_patch
    path: str | None = None  # set directly for recorded patches
    content: str | None = None


@dataclass
class CourtResult:
    first: Verdict
    final: Verdict
    parity: dict
    repairs: dict
    passed: bool
    attempts: list[dict] = field(default_factory=list)


# --- working copy and seeded defects --------------------------------------------------------------


def prepare_working_copy(source: Path, work_api: Path) -> Path:
    """Copy the committed API into the run's working folder. bin/obj stay for fast incremental
    builds; files are copied without their old timestamps so MSBuild always sees them as changed."""
    work_api.mkdir(parents=True, exist_ok=True)
    rules = work_api / "Rules"
    if rules.is_dir():
        for stale in rules.glob("*.cs"):
            stale.unlink()
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if path.is_dir() or rel.parts[0] in ("bin", "obj", "tests"):
            continue
        target = work_api / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return work_api


def seed_defect(work_api: Path, name: str) -> dict:
    spec = DEFECTS.get(name)
    if spec is None:
        raise RepairError(f"Unknown seeded defect {name!r}. Known: {', '.join(DEFECTS)}.")
    rule_file = work_api / "Rules" / f"{spec['rule']}.cs"
    text = rule_file.read_text(encoding="utf-8")
    start, end = _method_body(text, rule_file.name)
    body = text[start:end]
    matches = list(GREATER_THAN.finditer(body))
    if len(matches) != 1:
        raise RepairError(
            f"Seeded defect '{name}' expects exactly one '>' in {spec['rule']}'s method body, "
            f"found {len(matches)}. Refusing to guess."
        )
    m = matches[0]
    new_text = text[:start] + body[: m.start()] + spec["to"] + body[m.end():] + text[end:]
    _write(rule_file, new_text)
    before = _line_at(text, start + m.start()).strip()
    after = _line_at(new_text, start + m.start()).strip()
    return {
        "name": name,
        "ruleId": spec["rule"],
        "file": f"Rules/{rule_file.name}",
        "before": before,
        "after": after,
        "description": spec["description"],
    }


def _method_body(text: str, name: str) -> tuple[int, int]:
    signature = text.find("public static", text.find("public static class") + 1)
    brace = text.find("{", signature)
    if signature < 0 or brace < 0:
        raise RepairError(f"Could not find the rule method in {name}.")
    depth = 0
    for i in range(brace, len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return brace + 1, i
    raise RepairError(f"Unbalanced braces in {name}.")


def _line_at(text: str, index: int) -> str:
    return text[text.rfind("\n", 0, index) + 1 : (text.find("\n", index) + 1 or len(text) + 1) - 1]


# --- patches --------------------------------------------------------------------------------------


def propose_patch(
    client: LLMClient, rule: dict, rel_path: str, current: str, failures: str, previous: str, recorded_dir: Path
) -> Patch | None:
    """Ask the LLM (cache first). If no LLM answer is available, fall back to a recorded patch that was
    recorded against exactly this file. Returns None when there is no source at all."""
    template = PROMPT_FILE.read_text(encoding="utf-8")
    values = {
        "id": rule["id"],
        "rule": rule["rule"],
        "formula": rule["formula"],
        "path": rel_path,
        "file": current.rstrip("\n"),
        "failures": failures,
        "previous": previous,
    }
    prompt = template
    for name, value in values.items():
        prompt = prompt.replace("{{" + name + "}}", value)

    live_before = client.live_calls
    try:
        entry = client.complete(prompt)
    except LLMError:
        recorded = load_recorded(recorded_dir, rule["id"])
        if recorded and recorded["beforeSha256"] == _sha(current):
            return Patch("replay", "recorded-patch", recorded.get("recordedFrom", {}), path=recorded["path"], content=recorded["content"])
        return None
    live = client.live_calls > live_before
    provenance = {"provider": entry.get("provider"), "model": entry.get("model"), "servedBy": entry.get("served_by")}
    return Patch("live" if live else "replay", "llm-api" if live else "llm-cache", provenance, reply=entry["response"])


def validate_patch(patch: Patch, rule_id: str, current: str) -> tuple[str, str]:
    """Return (relative path, new file text) or raise RepairError with the reason for rejecting it."""
    if patch.reply is not None:
        path_match = re.search(r"^FILE:\s*(.+?)\s*$", patch.reply, re.M)
        code_match = re.search(r"```(?:csharp|cs|c#)?[ \t]*\r?\n(.*?)```", patch.reply, re.S)
        if not path_match or not code_match:
            raise RepairError("The reply is not in the required format: a FILE: line and one code block.")
        path, content = path_match.group(1), code_match.group(1)
    else:
        path, content = patch.path or "", patch.content or ""

    expected = f"Rules/{rule_id}.cs"
    normalised = path.strip().replace("\\", "/")
    if normalised.startswith("/") or re.match(r"^[A-Za-z]:", normalised):
        raise RepairError(f"Patch path {path!r} is absolute. Only {expected} may be changed.")
    if ".." in PurePosixPath(normalised).parts:
        raise RepairError(f"Patch path {path!r} leaves the Rules folder. Only {expected} may be changed.")
    if normalised != expected:
        raise RepairError(f"Patch targets {path!r}, but the repair agent may change only {expected}.")

    content = content.replace("\r\n", "\n").rstrip("\n") + "\n"
    if not content.startswith(f"// Rule {rule_id}\n"):
        raise RepairError(f"The new file must still start with '// Rule {rule_id}'.")
    if f"public static class {rule_id}" not in content:
        raise RepairError(f"The new file must keep 'public static class {rule_id}'.")
    signature = next((l.strip() for l in current.splitlines() if l.strip().startswith("public static") and "(" in l), None)
    if signature and signature not in content:
        raise RepairError(f"The method signature changed; it must stay '{signature}'.")
    if re.search(r"\b(CLM|POL)-\d", content):
        raise RepairError("The new file mentions claim or policy IDs; special-casing reference cases is not allowed.")
    return expected, content


def apply_patch(work_api: Path, rel_path: str, content: str, rule_id: str) -> None:
    rules_dir = (work_api / "Rules").resolve()
    target = (work_api / rel_path).resolve()
    if target.parent != rules_dir or target.name != f"{rule_id}.cs":
        raise RepairError(f"Refusing to write {target}: patches may only touch {rules_dir / (rule_id + '.cs')}.")
    _write(target, content)


def load_recorded(recorded_dir: Path, rule_id: str) -> dict | None:
    path = recorded_dir / f"repair-{rule_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _record(recorded_dir: Path, rule_id: str, rel: str, before: str, after: str, patch: Patch, seeded: dict | None) -> None:
    """Keep the first successful LLM repair so it can be replayed offline (always labelled as a replay)."""
    path = recorded_dir / f"repair-{rule_id}.json"
    if path.exists():
        return
    recorded_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "ruleId": rule_id,
        "path": rel,
        "seededDefect": seeded["name"] if seeded else None,
        "beforeSha256": _sha(before),
        "afterSha256": _sha(after),
        "recordedFrom": {"source": patch.source, **patch.provenance},
        "note": "Replayed only when no LLM response is available and the rule file matches beforeSha256. "
        "Replays are logged with mode 'replay' and source 'recorded-patch'.",
        "content": after,
    }
    _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# --- the court run --------------------------------------------------------------------------------


def run_court(
    register: dict,
    *,
    run_dir: Path,
    client: LLMClient,
    seed: str | None = None,
    port: int = DEFAULT_PORT,
    source_api: Path = DEFAULT_API_DIR,
    recorded_dir: Path = RECORDED_DIR,
    max_attempts: int = MAX_ATTEMPTS,
    root: Path = ROOT,
    log: Callable[[str], None] = print,
    on_verdict: Callable[[str, Verdict], None] | None = None,
    on_attempt: Callable[[dict], None] | None = None,
) -> CourtResult:
    fixture_dir = Path(register["fixture"])
    if not fixture_dir.is_absolute():
        fixture_dir = root / fixture_dir
    cases_path = fixture_dir / CASES_FILE
    sha_start = _sha_file(cases_path)

    work_dir = run_dir / "work"
    work_api = prepare_working_copy(Path(source_api), work_dir / "api")
    seeded = seed_defect(work_api, seed) if seed else None
    if seeded:
        log(f"Seeded defect '{seed}' in the working copy: {seeded['file']}  {seeded['before']}  ->  {seeded['after']}")

    def court(stage: str) -> Verdict:
        verdict = judge(register, api_dir=work_api, port=port, work_dir=work_dir, root=root, log=log)
        if on_verdict:
            on_verdict(stage, verdict)
        return verdict

    first = court("initial")
    current = first
    attempts: list[dict] = []
    fixed: list[str] = []
    unresolved: list[str] = []
    rules_by_id = {r["id"]: r for r in register["rules"]}

    for rule_id in sorted({r for c in first.parity["cases"] if not c["pass"] for r in c["implicatedRules"]}):
        if _rule_status(current, rule_id) == "PASS":
            continue  # an earlier repair already fixed it
        rule, rel = rules_by_id[rule_id], f"Rules/{rule_id}.cs"
        rule_file = work_api / rel
        previous, resolved = "", False
        for n in range(1, max_attempts + 1):
            before = rule_file.read_text(encoding="utf-8")
            record: dict = {"attempt": n, "ruleId": rule_id, "at": now_iso()}
            patch = propose_patch(client, rule, rel, before, _failures(current, rule_id, rule), previous, recorded_dir)
            if patch is None:
                record |= {
                    "mode": "none",
                    "source": "none",
                    "outcome": "no patch available",
                    "detail": "No LLM answer (unreachable or not cached) and no recorded patch for this exact file.",
                }
                _log_attempt(attempts, record, on_attempt)
                break
            record |= {"mode": patch.mode, "source": patch.source, "provenance": patch.provenance}
            try:
                rel_path, content = validate_patch(patch, rule_id, before)
                apply_patch(work_api, rel_path, content, rule_id)
            except RepairError as e:
                record |= {"diff": "", "build": "not run", "outcome": "rejected", "detail": str(e)}
                _log_attempt(attempts, record, on_attempt)
                previous = f"\nYour previous reply was rejected: {e}\n"
                continue
            record["diff"] = _unified_diff(before, content, rel)
            try:
                verdict = court(f"attempt {n}")
            except JudgeError as e:
                _write(rule_file, before)
                record |= {"build": "failed", "outcome": "build failed", "detail": str(e)[:2000]}
                _log_attempt(attempts, record, on_attempt)
                previous = f"\nYour previous fix did not compile:\n{str(e)[:1500]}\n"
                continue
            status = _rule_status(verdict, rule_id)
            new_failures = sorted(_failed_ids(verdict) - _failed_ids(current))
            record |= {
                "build": "ok",
                "judge": {
                    "result": verdict.parity["summary"]["result"],
                    "casesPassed": verdict.parity["summary"]["cases"]["passed"],
                    "casesTotal": verdict.parity["summary"]["cases"]["total"],
                    "ruleStatus": status,
                    "newFailures": new_failures,
                },
            }
            if status == "PASS" and not new_failures:
                record["outcome"] = "fixed"
                _log_attempt(attempts, record, on_attempt)
                current, resolved = verdict, True
                fixed.append(rule_id)
                if patch.source != "recorded-patch":
                    _record(recorded_dir, rule_id, rel_path, before, content, patch, seeded)
                break
            _write(rule_file, before)
            record["outcome"] = "still failing"
            _log_attempt(attempts, record, on_attempt)
            previous = f"\nYour previous fix still failed: rule {rule_id} is {status}; new failures: {new_failures or 'none'}.\n"
        if not resolved:
            unresolved.append(rule_id)

    sha_end = _sha_file(cases_path)
    tamper = {"file": cases_path.name, "sha256Before": sha_start, "sha256After": sha_end, "unchanged": sha_start == sha_end}
    if not tamper["unchanged"]:
        tamper["message"] = f"{cases_path.name} changed during the run. The run fails: reference cases must never move."
    passed = current.passed and not unresolved and tamper["unchanged"]

    parity = copy.deepcopy(current.parity)
    for rule in parity["rules"]:
        if rule["id"] in unresolved:
            rule["status"] = "UNRESOLVED"
    parity["summary"]["result"] = "PASS" if passed else "FAIL"
    parity["seededDefect"] = seeded
    parity["initial"] = {
        "summary": first.parity["summary"],
        "failedCases": sorted(_failed_ids(first)),
        "redRules": [r["id"] for r in first.parity["rules"] if r["status"] == "FAIL"],
        "rules": [{"id": r["id"], "status": r["status"], "failedCases": r["failedCases"]} for r in first.parity["rules"]],
        "cases": [c for c in first.parity["cases"] if not c["pass"]],
    }
    parity["repair"] = {"maxAttempts": max_attempts, "attempts": len(attempts), "fixed": fixed, "unresolved": unresolved, "log": "repairs.json"}
    parity["tamperGuard"] = tamper

    repairs = {
        "runId": register.get("runId"),
        "seededDefect": seeded,
        "maxAttempts": max_attempts,
        "fixed": fixed,
        "unresolved": unresolved,
        "attempts": attempts,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    _write(run_dir / "parity.json", json.dumps(parity, indent=2, ensure_ascii=False) + "\n")
    _write(run_dir / "repairs.json", json.dumps(repairs, indent=2, ensure_ascii=False) + "\n")
    return CourtResult(first, current, parity, repairs, passed, attempts)


# --- helpers --------------------------------------------------------------------------------------


def _failures(verdict: Verdict, rule_id: str, rule: dict) -> str:
    keys = [i[:1].lower() + i[1:] for i in rule["inputs"]] + (["today"] if "Today()" in rule["formula"] else [])
    lines = []
    for case in verdict.parity["cases"]:
        if case["pass"] or rule_id not in case["implicatedRules"]:
            continue
        shown = ", ".join(f"{k} = {json.dumps(case['inputs'].get(k))}" for k in keys if k in case["inputs"])
        lines.append(f"- Case {case['id']}: {shown or 'see rule inputs'}")
        for name, d in case["diff"].items():
            lines.append(f"  {name}: expected {json.dumps(d['expected'])}, got {json.dumps(d['actual'])}")
    return "\n".join(lines)


def _rule_status(verdict: Verdict, rule_id: str) -> str:
    return next((r["status"] for r in verdict.parity["rules"] if r["id"] == rule_id), "NO CASES")


def _failed_ids(verdict: Verdict) -> set[str]:
    return {c["id"] for c in verdict.parity["cases"] if not c["pass"]}


def _unified_diff(before: str, after: str, rel: str) -> str:
    return "".join(
        difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{rel}", f"b/{rel}", n=1)
    )


def _log_attempt(attempts: list[dict], record: dict, on_attempt) -> None:
    attempts.append(record)
    if on_attempt:
        on_attempt(record)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
