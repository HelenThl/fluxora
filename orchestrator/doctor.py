"""fluxora doctor: pre-flight checks for a live demo. Read-only: it writes nothing to the repo."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import register
from .extract import ExtractError, build_register
from .generate import GenerateError, generate
from .judge import DEFAULT_PORT, port_in_use
from .llm import CACHE_DIR, LLMClient, LLMError, get_settings
from .repair import RECORDED_DIR, RepairError, prepare_working_copy, seed_defect
from .serve import DASHBOARD_DIST, DEFAULT_PORT as DASHBOARD_PORT

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_RUN = ROOT / "runs" / "20261108-143433"

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def run_checks(port: int = DEFAULT_PORT, root: Path = ROOT, offline: bool = False) -> list[tuple[str, str, str]]:
    checks: list[tuple[str, str, str]] = []
    add = lambda status, name, detail: checks.append((status, name, detail))  # noqa: E731

    # Python
    version = ".".join(map(str, sys.version_info[:3]))
    add(OK if sys.version_info >= (3, 11) else FAIL, "Python 3.11+", version)

    # .NET SDK
    sdks = _run(["dotnet", "--list-sdks"])
    if sdks is None:
        add(FAIL, ".NET 8 SDK", "`dotnet` is not on PATH. Install the .NET 8 SDK and open a new terminal.")
    else:
        eights = [line.split()[0] for line in sdks.splitlines() if line.startswith("8.")]
        add(OK if eights else FAIL, ".NET 8 SDK", ", ".join(eights) if eights else f"no 8.x SDK in: {sdks.strip() or 'none'}")

    # NuGet packages the generated API needs, so the first build can work offline
    if sdks is not None:
        missing = _missing_nuget_packages(root / "generated" / "api")
        add(
            OK if not missing else WARN,
            "NuGet packages cached",
            "all present" if not missing else f"missing {', '.join(missing)}: the first build needs network "
            "(run `dotnet build generated/api` once while online)",
        )

    # Ports
    add(FAIL if port_in_use(port) else OK, f"Port {port} free (judge)",
        f"in use: stop it or use --port {port + 10}" if port_in_use(port) else "free")
    add(WARN if port_in_use(DASHBOARD_PORT) else OK, f"Port {DASHBOARD_PORT} free (dashboard)",
        "in use: `fluxora serve --port <other>`" if port_in_use(DASHBOARD_PORT) else "free")

    # LLM settings and the offline cache
    settings = get_settings(offline=offline)  # as `fluxora demo --offline` would see them
    if not settings.offline:
        add(WARN, "LLM mode", f"live: {settings.provider}, {settings.model} (check .env). `fluxora demo` will call the "
            "API on any cache miss; for a repeatable offline stage run use `fluxora demo --offline`")
    else:
        add(OK, "LLM mode", "offline: answers come from the committed cache only")
    cached_models = sorted({json.loads(p.read_text(encoding="utf-8")).get("model") for p in CACHE_DIR.glob("*.json")})
    if settings.offline and settings.model and settings.model not in cached_models:
        add(FAIL, "LLM_MODEL vs cache",
            f"LLM_MODEL={settings.model!r} but no key, and the cache holds {', '.join(cached_models)}. Unset LLM_MODEL (check .env).")
    status, name, detail = _cache_covers_demo(root)
    if status == FAIL and not settings.offline:
        status, detail = WARN, f"{detail} Without --offline the demo will make live calls for these prompts."
    add(status, name, detail)

    # Recorded repair patch (offline fallback for the seeded defect)
    add(*_recorded_patch_matches(root))

    # Reference cases still the ones the committed run was judged against
    cases = root / "fixtures" / "claim-triage" / "reference-cases.json"
    parity = REFERENCE_RUN / "parity.json"
    if parity.is_file():
        expected = json.loads(parity.read_text(encoding="utf-8"))["referenceCases"]["sha256Before"]
        actual = hashlib.sha256(cases.read_bytes()).hexdigest()
        add(OK if actual == expected else WARN, "Reference cases unchanged",
            f"sha256 {actual[:12]}" + ("" if actual == expected else f" differs from the reference run ({expected[:12]})"))

    # Optional: dashboard
    built = (DASHBOARD_DIST / "index.html").is_file()
    add(OK if built else WARN, "Dashboard built",
        "dashboard/dist ready" if built else "only needed for `fluxora serve` and `demo --pause`: cd dashboard && npm install && npm run build")
    return checks


def _run(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _missing_nuget_packages(api_dir: Path) -> list[str]:
    folder = os.environ.get("NUGET_PACKAGES")
    if not folder:
        listing = _run(["dotnet", "nuget", "locals", "global-packages", "--list"]) or ""
        m = re.search(r"global-packages:\s*(.+)", listing)
        folder = m.group(1).strip() if m else str(Path.home() / ".nuget" / "packages")
    packages = Path(folder)
    missing = []
    for project in sorted(api_dir.glob("*.csproj")):
        for name, version in re.findall(r'PackageReference Include="([^"]+)" Version="([^"]+)"', project.read_text(encoding="utf-8")):
            if not (packages / name.lower() / version.lower()).is_dir():
                missing.append(f"{name} {version}")
    return missing


def _cache_covers_demo(root: Path) -> tuple[str, str, str]:
    """Run extract and generate in memory, offline, to prove every LLM prompt is in the cache."""
    settings = get_settings(offline=True)
    client = LLMClient(settings, log=lambda _: None)
    try:
        reg = build_register(root / "fixtures" / "claim-triage", client).register
        reg["fixture"] = "fixtures/claim-triage"
        register.approve(reg, approve_all=True, reject=[])
        generate(reg, client, root=root)
    except (LLMError, ExtractError, GenerateError) as e:
        return FAIL, "Cache covers the demo", str(e)[:500]
    return OK, "Cache covers the demo", f"{client.cache_hits} extract and generate prompts answered offline"


def _recorded_patch_matches(root: Path) -> tuple[str, str, str]:
    recorded = RECORDED_DIR / "repair-R09.json"
    if not recorded.is_file():
        return WARN, "Recorded repair patch", "orchestrator/recorded/repair-R09.json is missing (offline repair relies on the cache only)"
    patch = json.loads(recorded.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        try:
            work = prepare_working_copy(root / "generated" / "api", Path(tmp) / "api")
            seed_defect(work, "threshold")
        except RepairError as e:
            return FAIL, "Recorded repair patch", f"seeding the defect failed: {e}"
        seeded = (work / "Rules" / "R09.cs").read_text(encoding="utf-8")
    matches = hashlib.sha256(seeded.encode("utf-8")).hexdigest() == patch["beforeSha256"]
    return (OK if matches else WARN, "Recorded repair patch",
            "matches the seeded R09 file" if matches else "recorded for a different R09 file; offline repair relies on the cache")
