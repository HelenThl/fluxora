"""Verify: Parity Court.

Builds and starts the migrated API, sends it every reference case over HTTP, and compares the answer
field by field with the expected output (money as exact decimals, errors as a set). Writes the
evidence to runs/<run-id>/parity.json. The judge never edits reference cases, tests or rules.json,
and it always stops the API it started.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .register import now_iso

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_DIR = ROOT / "generated" / "api"
DEFAULT_PORT = 5080
CASES_FILE = "reference-cases.json"
FIELDS = ("errors", "excess", "payable", "lateReport", "status")
OUTPUT_FIELDS = {"Errors": "errors", "Excess": "excess", "Payable": "payable", "LateReport": "lateReport", "Status": "status"}
HEALTH_TIMEOUT_SECONDS = 60
BUILD_TIMEOUT_SECONDS = 300
NO_DOTNET = (
    "The .NET 8 SDK was not found: `dotnet` is not on PATH. Install the .NET 8 SDK "
    "(https://dotnet.microsoft.com/download/dotnet/8.0), open a new terminal, and check with `dotnet --list-sdks`."
)
_MISSING = object()


class JudgeError(RuntimeError):
    pass


@dataclass
class Verdict:
    parity: dict
    passed: bool


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def judge(
    register: dict,
    *,
    api_dir: Path = DEFAULT_API_DIR,
    port: int = DEFAULT_PORT,
    work_dir: Path,
    root: Path = ROOT,
    log=print,
) -> Verdict:
    fixture_dir = Path(register["fixture"])
    if not fixture_dir.is_absolute():
        fixture_dir = root / fixture_dir
    cases_path = fixture_dir / CASES_FILE
    sha_before = sha256_file(cases_path)
    raw = cases_path.read_text(encoding="utf-8")
    exact_cases = json.loads(raw, parse_float=Decimal)["cases"]
    echo_cases = json.loads(raw)["cases"]
    owners = _owners(register["rules"])

    started = time.perf_counter()
    log(f"  build: dotnet build {_display(api_dir, root)}")
    dll = _build(Path(api_dir))
    built = time.perf_counter()

    if port_in_use(port):
        raise JudgeError(
            f"Port {port} is already in use. Stop whatever is listening there; "
            "the judge only tests an API it started itself."
        )
    url = f"http://127.0.0.1:{port}"
    work_dir.mkdir(parents=True, exist_ok=True)
    log_path = work_dir / "api.log"
    with open(log_path, "wb") as api_log:
        log(f"  start: {dll.name} on {url}")
        try:
            process = subprocess.Popen(
                ["dotnet", str(dll), "--urls", url], cwd=dll.parent, stdout=api_log, stderr=subprocess.STDOUT
            )
        except FileNotFoundError:
            raise JudgeError(NO_DOTNET) from None
        try:
            _wait_until_healthy(url, process, log_path)
            ready = time.perf_counter()
            log(f"  judge: {len(exact_cases)} reference cases")
            results = [_judge_case(url, exact, echo, owners) for exact, echo in zip(exact_cases, echo_cases)]
            finished = time.perf_counter()
        finally:
            _stop(process)
    log("  stop: API stopped")

    sha_after = sha256_file(cases_path)
    rules = _rollup(register["rules"], results)
    tampered = sha_after != sha_before
    cases_passed = sum(1 for r in results if r["pass"])
    rules_passed = sum(1 for r in rules if r["status"] == "PASS")
    passed = cases_passed == len(results) and not tampered and all(r["status"] != "FAIL" for r in rules)

    parity = {
        "runId": register.get("runId"),
        "judgedAt": now_iso(),
        "api": {"project": _display(api_dir, root), "url": url},
        "referenceCases": {
            "path": _display(cases_path, root),
            "sha256Before": sha_before,
            "sha256After": sha_after,
            "unchanged": not tampered,
        },
        "timings": {
            "buildSeconds": round(built - started, 2),
            "startupSeconds": round(ready - built, 2),
            "casesSeconds": round(finished - ready, 2),
            "totalSeconds": round(finished - started, 2),
        },
        "summary": {
            "result": "PASS" if passed else "FAIL",
            "cases": {"passed": cases_passed, "failed": len(results) - cases_passed, "total": len(results)},
            "rules": {"passed": rules_passed, "failed": sum(1 for r in rules if r["status"] == "FAIL"), "total": len(rules)},
        },
        "rules": rules,
        "cases": results,
    }
    return Verdict(parity, passed)


def write_parity(verdict: Verdict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(verdict.parity, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- the API process ------------------------------------------------------------------------------


def _build(api_dir: Path) -> Path:
    projects = sorted(api_dir.glob("*.csproj"))
    if len(projects) != 1:
        raise JudgeError(f"Expected one .csproj in {api_dir}, found {len(projects)}.")
    try:
        result = subprocess.run(
            ["dotnet", "build", str(projects[0]), "-nologo", "-v", "q", "-clp:NoSummary"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=BUILD_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise JudgeError(NO_DOTNET) from None
    except subprocess.TimeoutExpired:
        raise JudgeError(
            f"dotnet build did not finish within {BUILD_TIMEOUT_SECONDS}s. The first build downloads NuGet packages; "
            "check the network, or run `dotnet build generated/api` once beforehand so later builds work offline."
        ) from None
    if result.returncode != 0:
        lines = [l for l in (result.stdout + result.stderr).splitlines() if "error" in l.lower()]
        detail = "\n".join(dict.fromkeys(lines)) or (result.stdout + result.stderr)[-2000:]
        hint = ""
        if any(code in detail for code in ("NU1101", "NU1301", "NU1102")):
            hint = "\nNuGet packages could not be restored. The first build needs network access to nuget.org."
        raise JudgeError(f"dotnet build failed:\n{detail}{hint}")
    dll = api_dir / "bin" / "Debug" / "net8.0" / f"{projects[0].stem}.dll"
    if not dll.is_file():
        raise JudgeError(f"Build succeeded but {dll} is missing.")
    return dll


def _wait_until_healthy(url: str, process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise JudgeError(f"The API exited with code {process.returncode} before it was ready:\n{_tail(log_path)}")
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError, socket.timeout):
            pass
        time.sleep(0.25)
    raise JudgeError(f"The API did not answer GET /health within {HEALTH_TIMEOUT_SECONDS}s:\n{_tail(log_path)}")


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _tail(path: Path, lines: int = 20) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no API log)"


# --- comparing one case ---------------------------------------------------------------------------


def _judge_case(url: str, exact_case: dict, echo_case: dict, owners: dict[str, set[str]]) -> dict:
    inputs = dict(echo_case["inputs"])
    body = {k: v for k, v in inputs.items() if k != "today"} | {"asOf": inputs["today"]}
    request = urllib.request.Request(
        f"{url}/claims/evaluate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read().decode("utf-8")
        actual_exact = json.loads(text, parse_float=Decimal)
        actual_echo = json.loads(text)
    except urllib.error.HTTPError as e:
        detail = e.read(500).decode("utf-8", "replace")
        actual_exact = actual_echo = {"httpStatus": e.code, "body": detail}

    expected_exact, expected_echo = exact_case["expected"], echo_case["expected"]
    diff = {}
    for name in FIELDS:
        want, got = expected_exact.get(name), actual_exact.get(name, _MISSING)
        if not _same(name, want, got):
            diff[name] = {"expected": expected_echo.get(name), "actual": actual_echo.get(name)}

    rule_ids = list(exact_case["ruleIds"])
    implicated: list[str] = []
    if diff:
        owning = {r for name in diff for r in owners.get(name, set())} & set(rule_ids)
        fired = set(actual_exact.get("firedRules") or [])
        implicated = sorted((owning & fired) or owning or set(rule_ids))

    return {
        "id": exact_case["id"],
        "ruleIds": rule_ids,
        "description": exact_case.get("description", ""),
        "oracle": exact_case.get("oracle", "manual"),
        "inputs": echo_case["inputs"],
        "expected": expected_echo,
        "actual": actual_echo,
        "diff": diff,
        "implicatedRules": implicated,
        "pass": not diff,
    }


def _same(name: str, want: object, got: object) -> bool:
    if got is _MISSING:
        return False
    if name == "errors":
        return isinstance(got, list) and set(want or []) == set(got)
    if name in ("excess", "payable"):
        if want is None or got is None:
            return want is None and got is None
        if isinstance(got, bool) or not isinstance(got, (int, Decimal)):
            return False
        return Decimal(got) == want
    if name == "lateReport":
        return (want is None and got is None) or (isinstance(got, bool) and got == want)
    return want == got


def _owners(rules: list[dict]) -> dict[str, set[str]]:
    """Which rules decide each response field, from each rule's register `output`."""
    owners: dict[str, set[str]] = {}
    for rule in rules:
        for output in (o.strip() for o in rule["output"].split(",")):
            field_name = OUTPUT_FIELDS.get(output, output[:1].lower() + output[1:])
            owners.setdefault(field_name, set()).add(rule["id"])
    return owners


def _rollup(rules: list[dict], results: list[dict]) -> list[dict]:
    rollup = []
    for rule in rules:
        citing = [c for c in results if rule["id"] in c["ruleIds"]]
        failed = [c["id"] for c in citing if not c["pass"] and rule["id"] in c["implicatedRules"]]
        oracles = sorted({c["oracle"] for c in citing})
        rollup.append(
            {
                "id": rule["id"],
                "rule": rule["rule"],
                "casesTotal": len(citing),
                "casesFailed": len(failed),
                "status": "NO CASES" if not citing else ("FAIL" if failed else "PASS"),
                "oracle": oracles[0] if len(oracles) == 1 else ("mixed" if oracles else "-"),
                "failedCases": failed,
            }
        )
    return rollup


def _display(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()
