# Fluxora — project brief for Claude Code

**Fluxora: Transform. Rebuild. Verify.**

EXL x UCD Data & AI Hackathon 2026, Challenge 02: Agentic Power Platform migration.
Submission deadline: Fri 13 Nov 2026, 23:59 Irish time. Target: working build by end of Mon 9 Nov.

## What we are building

Fluxora takes a Power App (screens, Power Fx formulas, one Power Automate flow, a Dataverse schema), migrates it to React + .NET Core + Cosmos DB, and then **proves the migrated app behaves the same, rule by rule**.

The proof is the product. We call it **Parity Court**. Every other part of the build exists to feed it.

Tagline: **Transform. Rebuild. Verify.** The three words map to the three agents: Extractor (transform the app into an approved rule register), Generator (rebuild it on React, .NET and Cosmos DB), and Judge (verify it in Parity Court). Use these words in the dashboard nav, CLI help text and README so the product reads as one idea.

Pitch line: *"We don't just migrate apps. We show you the proof."*

## Guiding principle: simple and unique beats complex

- One sample app, one flow, one pipeline, three agents.
- Prefer a boring, working path over a clever, fragile one.
- If a feature isn't on the milestone list, don't build it. Ask first.
- The demo must run offline from committed artefacts. Live LLM calls are a bonus, not a dependency.

## Out of scope (do not build)

UI fidelity / screenshot comparison, PDF reports, a second app, auth/login, Azure deployment, IaC, MLflow/Azure ML, multi-tenant anything, a plugin system, generic support for all Power Fx functions.

## The pipeline

```
fixture export ──► Extractor ──► Rule Register ──► human approve ──► Generator ──► migrated app
                                                                                     │
                       reference cases (Power Fx oracle or manual) ──► Judge / Parity Court
                                                                                     │
                                                         mismatch ──► bounded repair (max 3)
                                                                                     │
                                                                           evidence page
```

### Agent 1: Extractor
Reads the fixture export and writes `runs/<run-id>/rules.json`. Each rule:

```json
{
  "id": "R09",
  "source": { "file": "flow.json", "ref": "actions.Condition_Amount" },
  "formula": "ClaimAmount > 5000",
  "rule": "Claims over £5,000 are routed to a manager for approval.",
  "inputs": ["ClaimAmount"],
  "output": "Status",
  "confidence": "high",
  "status": "pending"
}
```

Unsupported constructs go into `rules.json` under `"unsupported": [...]` with the reason. Never drop them silently.

### Human gate
The dashboard shows the register with Approve / Reject per rule. Only `approved` rules flow to the Generator. Approvals are timestamped in `rules.json`.

### Agent 2: Generator
From approved rules only, generate:
- `generated/api/`: .NET 8 minimal API. `POST /claims/evaluate` returns the computed fields (excess, payable, flags, status). Each rule is one small C# method with a `// Rule R0x` comment, for traceability.
- `generated/api` data layer: a Cosmos DB `Claim` document model behind an `IClaimRepository`. Use the Cosmos emulator if available; otherwise an in-memory implementation selected by config. Do not burn time on emulator setup.
- `generated/web/`: one React + TypeScript form (Vite) that mirrors the Power App screen and calls the API.

Generated code is **committed**, so the demo never depends on a live LLM call.

### Agent 3: Judge (Parity Court + repair)
1. Load `fixtures/claim-triage/reference-cases.json`.
2. Call the migrated API for each case and compare it field by field with the expected output.
3. Write `runs/<run-id>/parity.json` with case id, rule ids, inputs, expected, actual, pass/fail and the oracle source (`powerfx-engine` or `manual`).
4. On failure, run the repair loop. Send the failing rule, its C# method and the diff to the LLM, apply the patch, rebuild and re-judge. **Max 3 attempts.** Log every attempt (diff, result) to `runs/<run-id>/repairs.json`.

Hard rules for repair:
- The repair agent may only modify files under `generated/api/Rules/`.
- It must never modify reference cases, tests or the rule register. Enforce this: hash `reference-cases.json` before and after, and fail the run if the hash changes.
- After 3 failed attempts, mark the rule `unresolved`. Never mark it passing.

### Seeded defect (the demo moment)
`fluxora judge --seed-defect threshold` deterministically changes `>` to `>=` in Rule R09's C# method before judging. Parity Court must go red on the £5,000 boundary case, the repair loop must fix it, and the result must go green. This has to work reliably every time.

## Reference oracle

First choice: evaluate the original Power Fx formulas with Microsoft's open-source Power Fx engine (NuGet `Microsoft.PowerFx.Interpreter`) in a small .NET console under `oracle/`. **Time-box this to 2 hours.**

Fallback: hand-write the expected values in `reference-cases.json` with `"oracle": "manual"`. The dashboard must show which oracle produced each expectation. Reference cases must never be generated by the same LLM that generates the code.

## Sample app fixture: claim triage (build this first)

We may not have a real export tonight, so build a synthetic one in `fixtures/claim-triage/` that mirrors the shape of a real one:
- `app.pa.yaml`: one screen (`ClaimScreen`) with controls and Power Fx, loosely following `pac canvas unpack` output. It does not need to be byte-exact.
- `flow.json`: a Power Automate (Logic Apps-style) definition with an amount condition and a late-report condition.
- `dataverse-schema.json`: a `Claim` table.
- `reference-cases.json`: 2–3 cases per rule, **including boundary values** (5000, 5000.01, day 30, day 31, amount equal to excess).

**Claim fields:** ClaimId, PolicyNumber, ClaimType (Motor | Home | Travel), PolicyStartDate, IncidentDate, ReportedDate, ClaimAmount, HasReceipt, Status.

**Rules:**

| ID | Where | Power Fx / condition | Behaviour |
|---|---|---|---|
| R01 | App | `IsBlank(ClaimAmount) \|\| ClaimAmount <= 0` | Error: amount must be greater than zero |
| R02 | App | `Not(ClaimType in ["Motor","Home","Travel"])` | Error: invalid claim type |
| R03 | App | `IncidentDate > Today()` | Error: incident date cannot be in the future |
| R04 | App | `IncidentDate < PolicyStartDate` | Status = "Not covered" |
| R05 | App | `Switch(ClaimType,"Motor",250,"Home",350,"Travel",100)` | Excess |
| R06 | App | `Max(0, ClaimAmount - Excess)` | Payable |
| R07 | App | `Payable = 0` | Status = "Below excess" |
| R08 | App | `ClaimType = "Travel" && ClaimAmount > 2000 && !HasReceipt` | Error: receipt required |
| R09 | Flow | `ClaimAmount > 5000` | Status = "Pending approval" (manager) |
| R10 | Flow | `DateDiff(IncidentDate, ReportedDate, Days) > 30` | LateReport = true; Status = "Manual review" |
| R11 | Flow | otherwise | Status = "Approved" |

Precedence: validation errors (R01–R03, R08) → Not covered (R04) → Below excess (R07) → Manual review (R10) → Pending approval (R09) → Approved (R11). Put this order in the fixture explicitly so it is testable.

All data is synthetic. No real names, policy numbers or personal data anywhere.

## Stack

| Part | Choice |
|---|---|
| Orchestrator + agents | Python 3.11, single CLI `fluxora` (Typer), prompts in `orchestrator/prompts/*.md` |
| LLM | Provider set by env var (`LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`); one thin client module |
| Migrated backend | .NET 8 minimal API, xUnit |
| Migrated frontend | React + TypeScript + Vite |
| Data | Cosmos DB model; emulator or in-memory via config |
| Dashboard | React + TypeScript + Vite + Tailwind; reads `runs/<run-id>/*.json` |
| Oracle | .NET console with Microsoft.PowerFx (or manual fallback) |

## Repo layout

```
fluxora/
  CLAUDE.md  README.md  AI_USAGE.md
  fixtures/claim-triage/
  orchestrator/        # cli.py, extract.py, generate.py, judge.py, repair.py, llm.py, prompts/
  oracle/              # Power Fx evaluator (optional)
  generated/api/       # .NET 8 API (Rules/, Data/, tests/)
  generated/web/       # React form
  dashboard/           # Transform / Rebuild / Verify views
  runs/<run-id>/       # rules.json, parity.json, repairs.json, evidence.md
```

## CLI

```
fluxora extract  fixtures/claim-triage      # -> runs/<id>/rules.json
fluxora approve  <run-id> [--all]           # CLI fallback for the dashboard gate
fluxora generate <run-id>                   # -> generated/
fluxora judge    <run-id> [--seed-defect threshold]
fluxora evidence <run-id>                   # -> runs/<id>/evidence.md
fluxora demo                                # full scripted run for the video
```

## Milestones (do them in order and commit after each)

| # | Milestone | Done when |
|---|---|---|
| M0 | Repo scaffold + fixture | All fixture files exist; `reference-cases.json` covers every rule, with boundaries |
| M1 | Oracle spike (2h max) | Power Fx engine evaluates R05, R06 and R09 for real, or the fallback is decided and noted in README |
| M2 | Extractor | `extract` produces 11 rules with source refs from the fixture; unsupported list present |
| M3 | Generator | `generate` emits an API that builds, a React form that runs, and the Cosmos model; xUnit tests pass |
| M4 | Judge | `judge` produces `parity.json`; all cases green on clean generated code |
| M5 | Seeded defect + repair | `judge --seed-defect threshold` goes red on R09, repairs within 3 attempts, goes green; `repairs.json` logged; hash guard works |
| M6 | Dashboard + evidence | Three views named after the tagline: **Transform** (Rule Register, approve/reject), **Rebuild** (generated files, linked to rule IDs), **Verify** (Parity Court red/green with oracle label, plus the evidence summary: approvals, repairs, unsupported items, data notes) |
| M7 | `demo` command + README | Fresh clone → README steps → `fluxora demo` works end to end |

If time runs short, keep M0–M5 and make M6 a single static page. A red-to-green Parity Court on the terminal still beats a pretty dashboard that doesn't work.

## Working conventions for Claude Code

- Work one milestone at a time. At the end of each, run the checks, summarise what changed, and stop for review.
- Keep it small: no new dependencies without a reason, no abstractions for hypothetical future apps.
- Every C# rule method carries its rule ID. Every parity result carries rule IDs. Traceability is non-negotiable.
- Never weaken, skip or delete a test to make something pass.
- Record each AI-assisted step in `AI_USAGE.md` (tool, what it produced, what a human changed). The submission requires us to declare AI tools.
- Never put real personal data in fixtures, prompts or logs.

## Measure for the pitch (Business Impact is 30%)

`fluxora demo` prints wall-clock time per stage plus the total, and the evidence page shows it. Use only measured numbers in the pitch. Never estimate.
