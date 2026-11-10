# Fluxora

**Transform. Rebuild. Verify.**

*We don't just migrate apps. We show you the proof.*

Fluxora migrates a Power Platform app (a canvas app's screens and Power Fx, a Power Automate flow and
a Dataverse table) to React + .NET 8 + Cosmos DB, then **proves the migrated app behaves the same,
rule by rule**.

- **Transform:** an Extractor turns the app into a rule register that a person approves.
- **Rebuild:** a Generator writes the new code from the approved rules only.
- **Verify:** a Judge runs the migrated API against reference cases whose expected results were
  confirmed by Microsoft's own Power Fx engine. Any rule that disagrees goes red in **Parity Court**,
  and a bounded repair agent fixes it.

Everything is traceable: rule ID → C# file → parity result → evidence page. It runs fully offline
from committed artefacts.

EXL x UCD Data & AI Hackathon 2026, Challenge 02 (Agentic Power Platform migration). The sample app,
claim triage, is synthetic. There are no real names, policy numbers or personal data anywhere.

## Architecture

```
  Power App export (synthetic)                    Reference cases (32)
  app.pa.yaml · flow.json · dataverse-schema       expected results confirmed by
            │                                      the Power Fx engine (oracle/)
            ▼                                                  │
  ┌─ TRANSFORM ───────────────────────┐                        │
  │ Extractor: code parses every rule; │──► runs/<id>/rules.json
  │ LLM writes only the plain-English  │    (11 rules, precedence,
  │ sentence + confidence              │     2 unsupported items)
  └─────────────────┬──────────────────┘                        │
                    ▼                                           │
        human approval gate (dashboard or CLI)                  │
                    ▼                                           │
  ┌─ REBUILD ─────────────────────────┐                         │
  │ Generator: templates + one LLM-    │──► generated/api  (.NET 8, Cosmos DB model, xUnit)
  │ written method body per rule       │    generated/web  (React form)
  └─────────────────┬──────────────────┘                        │
                    ▼                                           ▼
  ┌─ VERIFY ─────────────────────────────────────────────────────────────┐
  │ Judge / Parity Court: build + run the API, POST every case, compare   │──► parity.json
  │ field by field ── mismatch ──► repair agent (max 3, Rules/ only) ──┐  │──► repairs.json
  │                ◄──────────────── rebuild, re-judge ◄───────────────┘  │
  └─────────────────────────────────┬────────────────────────────────────┘
                                    ▼
                    evidence.md + dashboard (Transform / Rebuild / Verify)
```

## Prerequisites

| Tool | Version | Checked with |
|---|---|---|
| Git | any | |
| Python | 3.11 or newer | 3.12.10 |
| .NET SDK | 8.x | 8.0.427 |
| Node.js + npm | 20 or newer (only for the dashboard and the React form) | 24.19 |

`fluxora demo` needs Python and the .NET 8 SDK. It also needs network access the first time, so pip
and NuGet can download packages. After that it runs offline, and you don't need an LLM API key.

## Setup from a fresh clone

```bash
git clone <repo-url> fluxora
cd fluxora
python -m venv .venv
source .venv/bin/activate              # macOS / Linux
# source .venv/Scripts/activate        # Windows, Git Bash
# .venv\Scripts\Activate.ps1           # Windows, PowerShell
pip install -e ".[dev]"
```

Optional: build the dashboard. You need it for `fluxora serve` and `fluxora demo --pause`.

```bash
cd dashboard
npm install
npm run build
cd ..
```

Optional: use a live LLM. Copy `.env.example` to `.env` and fill in `LLM_PROVIDER` (`anthropic`
or `openai`), `LLM_API_KEY` and `LLM_MODEL`. `LLM_BASE_URL` is only for OpenAI-compatible endpoints.
Without a key, everything is answered from the committed cache.

## Run the demo

Check the machine first. This is read-only and takes a few seconds:

```bash
fluxora doctor
```

It checks Python, the .NET 8 SDK, the NuGet packages for an offline first build, free ports, your
LLM settings (for example `LLM_MODEL` set without a key), that the committed cache answers every
prompt, the recorded repair patch, and whether the dashboard is built. It ends READY, READY WITH
WARNINGS or NOT READY, and names the fix.

If your `.env` has a live key you want to keep, run the demo with `--offline` and point `LLM_MODEL`
at the committed cache's model for that shell (a real environment variable wins over `.env`):

```bash
export LLM_MODEL=claude-code:claude-opus-5-5   # PowerShell: $env:LLM_MODEL = "claude-code:claude-opus-5-5"
fluxora doctor --offline
fluxora demo --offline
```

```bash
fluxora demo
```

It runs the whole pipeline in eight timed stages:

1. **Transform: extract.** 11 rules and 2 unsupported items, in a new run under `runs/<run-id>/`.
2. **Transform: approval gate.** This is auto-approved, and the demo says so loudly. Use
   `fluxora demo --pause` to approve each rule yourself in the dashboard.
3. **Rebuild: generate.** 33 files go into `runs/<run-id>/generated/`. The demo also checks they are
   byte-identical to the committed `generated/` code.
4. **Rebuild: migrate data.** The 40 synthetic Dataverse rows in
   `fixtures/claim-triage/dataverse-records.json` become Cosmos DB `Claim` documents
   (`runs/<run-id>/migrated-claims.json`). The mapping comes from `dataverse-schema.json`, and the
   documents are checked against the generated `ClaimDocument.cs`. 7 rows carry planted problems
   (a duplicate claim ID, an unknown option value, a missing amount, 3 decimal places, an over-long
   policy number, an impossible date). They are quarantined with a reason, never dropped or guessed.
   Reconciliation then reads the documents back: every row accounted for, unique ids, a field-by-field
   round trip, the money control total, counts by type and status, and the source file unchanged.
   `MIGRATION: PASS`, written to `migration.json`.
5. **Verify: replay migrated data.** Every migrated claim is sent to the migrated API, evaluated as of
   its reported date (the day the original app decided it), and the status that comes back is
   compared with the status Dataverse stored. 32/32 match; the one claim with no stored status is
   listed, not counted. `REPLAY: PASS`. Any mismatch is named per claim.
6. **Verify on clean code.** VERDICT: PASS, 32/32 cases and 11/11 rules.
7. **Verify with a seeded defect.** R09's `>` is changed to `>=` in a working copy, so a claim of
   exactly £5,000 wrongly goes to a manager. Parity Court goes red on that one case, and only R09 is
   blamed:

   ```
   R09   4/5    FAIL      powerfx-engine  If the claim amount is over £5,000, the claim's status is...
         R09-02  status: expected "Approved", got "Pending approval"
   INITIAL VERDICT: FAIL

   REPAIR  R09  attempt 1/3  [replay: cached LLM response]
     -        return (claimAmount ?? 0m) >= 5000m;
     +        return (claimAmount ?? 0m) > 5000m;
     -> fixed  cases 32/32
   FINAL VERDICT: PASS
   ```
8. **Evidence.** `runs/<run-id>/evidence.md` is written, including the migration and replay report.

It ends with a table of measured wall-clock times. Each row says whether the LLM answered live, from
the cache, or by replay. Here is the committed evidence run `runs/20261110-175816/`, offline with
the cached LLM in a Linux cloud container (2026-11-10), from a fresh clone. It is the median of five
runs; see [docs/measurements.md](docs/measurements.md) for all of them:

| Stage | Seconds | Mode |
|---|---|---|
| Transform: extract | 0.01 | cached LLM (11 responses, no API calls) |
| Transform: approval gate | 0.00 | auto-approved, no human |
| Rebuild: generate | 0.02 | cached LLM (11 responses, no API calls) |
| Rebuild: migrate data | 0.00 | no LLM |
| Verify: replay migrated data | 2.26 | no LLM; includes the run's first .NET build |
| Verify: judge clean code | 2.04 | no LLM (no repair needed) |
| Verify: seeded defect + repair | 3.68 | repair: cached LLM (1 attempt) |
| Evidence | 0.00 | no LLM |
| **Total** | **8.01** | |

`0.00` means under 5 milliseconds. The first run in a fresh clone took 10.60s.

Then look at the result:

```bash
fluxora serve <run-id>         # http://127.0.0.1:8765/ (build the dashboard first)
```

The exit code is 0 only if both the clean and the seeded Parity Court end green, the migration
reconciles and the replay matches.

## Commands, one stage at a time

```bash
fluxora extract fixtures/claim-triage             # Transform -> runs/<run-id>/rules.json
fluxora approve <run-id> --all [--reject R05]     # human gate, timestamped decisions
fluxora generate <run-id> [--offline]             # Rebuild -> generated/
fluxora judge <run-id>                            # Verify -> parity.json, repairs.json
fluxora judge <run-id> --seed-defect threshold    # the red-to-green moment
fluxora migrate <run-id> [--replay]               # Rebuild (data) -> migrated-claims.json, migration.json;
                                                  #   --replay also checks them through the migrated API
fluxora evidence <run-id>                         # -> runs/<run-id>/evidence.md
fluxora serve [<run-id>]                          # dashboard on http://127.0.0.1:8765/
fluxora doctor                                    # pre-flight checks before presenting
```

`runs/20261108-143433/` is the committed reference run, already approved, judged and repaired.
Runs that you create stay out of git.

### Transform

- **Parsed by code, not the LLM** (`orchestrator/extract.py`): each rule's source file and ref,
  formula, inputs, output, the status precedence, and the unsupported list.
- **Written by the LLM:** only the plain-English `rule` sentence and a `confidence` value
  (`orchestrator/prompts/extract_rule.md`).
- **Rule IDs:** pinned in `fixtures/claim-triage/rule-ids.json` so reference cases can cite stable IDs.
- **Unsupported constructs:** listed with a reason, never silently dropped.

### Rebuild

- **One file per approved rule:** `generated/api/Rules/R0x.cs` holds one static method, headed by
  `// Rule R0x` and the rule's sentence, source and formula.
- **Written by the LLM:** only the method body (`orchestrator/prompts/generate_rule.md`).
- **Rendered by code:** everything else. That includes `Evaluator.cs`, which applies the extracted
  precedence and holds no business values.
- **API:** `POST /claims/evaluate` (the nine Claim fields plus an optional `asOf`) and `GET /health`.
  Each claim is saved through `IClaimRepository`. `Storage:Provider` is `InMemory` by default;
  `Cosmos` uses `Microsoft.Azure.Cosmos`.
- **Skipped rules:** pending or rejected rules are left out and reported.
- **Repeatable:** offline reruns are byte-identical.
- **Running it by hand:** `dotnet run --project generated/api` serves the API on port 5080. Then run
  `npm install` and `npm run dev` in `generated/web` for the form on port 5173.

### Verify

- **Safe test runs:** the judge builds and starts the API itself (refusing an occupied port), always
  stops it, and works on a copy in `runs/<run-id>/work/`. Committed code is never edited.
- **Exact comparison:** every reference case is POSTed with `asOf` set to the case's date. Money is
  compared as exact decimals and `errors` as a set.
- **Blame:** a failure blames only the rules that own the field that diverged, narrowed to the rules
  that fired.
- **Repair:** at most 3 attempts per rule.
  - The reply must be the full replacement for `Rules/<rule>.cs`. Other paths, signature changes and
    special-cased claim or policy IDs are rejected.
  - After 3 failures the rule is `UNRESOLVED`, never PASS.
  - Every attempt is logged with its diff, and with mode `live` (a real call in this run) or `replay`
    (a cached response, or a recorded patch used only for the exact file it was recorded against).
- **Tamper guard:** `reference-cases.json` is hashed before and after the run. Any change fails the run.

## Oracle: where the expected results come from

The expected values in `fixtures/claim-triage/reference-cases.json` were checked with Microsoft's
open-source Power Fx engine (`Microsoft.PowerFx.Interpreter` 1.8.1), running the original formulas:

```bash
dotnet run --project oracle -- fixtures/claim-triage/reference-cases.json
```

- **R01–R08** are evaluated verbatim from `app.pa.yaml`.
- **R09 and R10** live in the flow as Logic Apps expressions, which are not Power Fx, so the engine
  runs their Power Fx equivalents from the project brief. R10 uses `TimeUnit.Days`.
- **R11 and status precedence** are our own encoding: one `If(...)` chain built from the rule formulas.
- **`Today()`** uses a fixed clock taken from each case's `today`.
- **Result:** all 32 cases matched on every field (160 of 160 values), so every case is labelled
  `powerfx-engine` and none rely on hand-written values alone. The dashboard shows the label on
  every expectation.

**What the oracle does not prove:**

- It doesn't prove the precedence chain or the R09/R10 Power Fx versions are what the business
  intended; it only checks the logic and arithmetic.
- It uses decimals throughout. Canvas Power Apps use floating point.

## What is not supported

These constructs are found in the sample app but not migrated, and both are listed in the register:

- **`Notify(...)`** in `ClaimScreen.btnSubmit.OnSelect`: an in-app toast. The React form shows the
  returned status instead.
- **`Send_an_email`** in the flow: an Office 365 connector call. There is no mail integration.

Out of scope by design:

- UI fidelity and screenshot comparison
- PDF reports
- a second app
- auth and login
- Azure deployment and IaC
- MLflow and Azure ML
- anything multi-tenant
- a plugin system
- generic support for all Power Fx functions

The parser understands this app's shapes: named formulas, `If`/`Switch` status chains, and simple
flow conditions. It is not a general Power Fx compiler.

## Tests and checks

```bash
pytest                                       # 90 tests; the judge, repair, demo and doctor tests need the .NET SDK
dotnet test generated/api/tests              # every reference case through the generated Evaluator
python scripts/check_fixture.py              # fixture coverage and boundary values
```

UI test of the migrated React form (needs Node.js and the .NET SDK). It starts the API and the form
on their own ports (5093 and 5174), fills the form in a real browser for every reference case, and
checks the status, excess, payable, late-report flag and errors on the page. The expected values
come from `reference-cases.json`, not from the test. 28 cases run. 4 are skipped with a printed
reason, because the form can't express them: a claim type outside the drop-down, or a result that
depends on a fixed "today". Parity Court covers those through the API.

```bash
cd generated/web
npm install
npx playwright install chromium              # once per machine
npm run test:ui                              # 28 passed, 4 skipped
cd ../..
```

The judge and demo tests start the generated API on fixed ports (5080 and 5091). Don't run
`pytest` while a `fluxora demo`, `fluxora judge` or another `pytest` is running on the same machine,
or both will see a busy port and fail.

## AI tools used

AI help is declared step by step in [AI_USAGE.md](AI_USAGE.md).

**No LLM API call made the committed artefacts.** The rule sentences, the C# method bodies and the
R09 repair patch were written by Claude in a Claude Code session, from the exact prompts the pipeline
sends. Their cache entries say so: provider `claude-code`, model `claude-code:claude-opus-5-5`. Every
stage that uses them is labelled "cached LLM" or "replay", never "live".

**To use a live model:** set `.env`. Cache keys include the model name, so a different model makes
real calls, caches its answers next to the committed ones, and is labelled "live LLM". With more than
one model in the cache, set `LLM_MODEL` for offline runs.

## Submission documents

- [docs/architecture.svg](docs/architecture.svg), rendered from
  [docs/architecture.mmd](docs/architecture.mmd): the pipeline, showing where an LLM is called and the
  human gate. To re-render it, from this folder:
  `npx -y @mermaid-js/mermaid-cli@11.4.2 -i docs/architecture.mmd -o docs/architecture.svg`
  (on Windows PowerShell with scripts disabled, use `npx.cmd` instead of `npx`).
- [docs/responsible-ai.md](docs/responsible-ai.md): data, privacy, oversight, safeguards, fairness,
  limitations, and what FCA and GDPR would still require.
- [docs/measurements.md](docs/measurements.md): measured demo timings, taken from real `evidence.md`
  files.
- [docs/demo-script.md](docs/demo-script.md): the 2:45 video script and pre-recording checklist.
- [docs/deck-outline.md](docs/deck-outline.md): the 10-slide deck outline.
- [AI_USAGE.md](AI_USAGE.md): AI used to build Fluxora, and the LLM calls Fluxora makes at runtime.

## Repository layout

```
fixtures/claim-triage/   synthetic Power App export, reference cases, pinned rule IDs
orchestrator/            the fluxora CLI: extract, generate, judge, repair, evidence, serve, demo
  prompts/               the three LLM prompts (extract_rule, generate_rule, repair_rule)
  templates/             deterministic parts of the generated API and form
  cache/                 committed LLM responses (offline demo)
  recorded/              recorded repair patch for offline replay
oracle/                  Power Fx engine checker for the reference cases
generated/api/           migrated .NET 8 API, Cosmos DB model, xUnit tests
generated/web/           migrated React form
dashboard/               Transform / Rebuild / Verify dashboard
runs/20261108-143433/    committed reference run: rules, parity, repairs, evidence
scripts/                 fixture check
```
