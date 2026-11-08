# Fluxora

**Transform. Rebuild. Verify.**

*We don't just migrate apps. We show you the proof.*

Fluxora migrates a Power App (screens, Power Fx, one Power Automate flow, a Dataverse schema) to
React + .NET 8 + Cosmos DB, then proves the migrated app behaves the same, rule by rule, in
**Parity Court**.

| Stage | Agent | Output |
|---|---|---|
| Transform | Extractor | `runs/<run-id>/rules.json`, the rule register a human approves |
| Rebuild | Generator | `generated/api/` (.NET 8 + Cosmos model) and `generated/web/` (React form) |
| Verify | Judge | `runs/<run-id>/parity.json`, plus `repairs.json` from the bounded repair loop |

> Status: **M5** (fixture, Power Fx oracle, Extractor, Generator, Parity Court, repair loop). Full run instructions arrive with M7.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # macOS/Linux: .venv/bin/pip
```

LLM settings come from `.env` (copy `.env.example`): `LLM_PROVIDER` (`anthropic` or `openai`),
`LLM_API_KEY`, `LLM_MODEL`, and optionally `LLM_BASE_URL` for an OpenAI-compatible endpoint.
Without a key, everything runs offline from the committed cache in `orchestrator/cache/`.

## Transform: rule register

```bash
fluxora extract fixtures/claim-triage              # -> runs/<run-id>/rules.json
fluxora extract fixtures/claim-triage --offline    # cache only, no API calls
fluxora approve <run-id> --all [--reject R05,R06]  # human gate, timestamped
```

How the register is built:

- **Parsed by code, not the LLM:** each rule's source file and ref, formula, inputs, output, the
  status precedence, and the `unsupported` list. Unsupported means the parser saw it but cannot
  migrate it, so it is listed rather than dropped.
- **Written by the LLM:** only the plain-English `rule` sentence and a `confidence` value, using
  `orchestrator/prompts/extract_rule.md`. Every reply is cached under `orchestrator/cache/`, keyed by
  model and prompt, and the cache is committed, so the demo needs no API key.
- **Rule IDs:** pinned in `fixtures/claim-triage/rule-ids.json`, so reference cases can cite stable
  IDs. The flow checks "late report" before "amount", so discovery order alone would not give the
  brief's numbering.
- **Where the cached sentences came from:** they were written in a Claude Code session from the
  exact prompts, not by an API call. Their cache entries say so: provider `claude-code`, model
  `claude-code:claude-opus-5-5`. To regenerate them with a live model, delete
  `orchestrator/cache/*.json`, fill in `.env`, and run `fluxora extract fixtures/claim-triage`.

## Rebuild: generated app

```bash
fluxora generate 20261108-143433 --offline   # approved rules -> generated/
dotnet test generated/api/tests              # every reference case through the Evaluator
dotnet run --project generated/api           # API on http://localhost:5080
cd generated/web && npm install && npm run dev   # form on http://localhost:5173
```

What gets generated:

- **One file per approved rule.** Each `generated/api/Rules/R0x.cs` holds a single static method
  plus its constants (status value or error message, taken from the fixture). Its header names the
  rule ID, the plain-English sentence, the source ref and the formula.
- **Written by the LLM:** only the statements inside each method.
- **Rendered by code:** everything else. That includes `Evaluator.cs`, which orders the rule calls
  by the precedence the Extractor read from the fixture and holds no business values.
- **API:** `POST /claims/evaluate` takes the nine Claim fields plus an optional `asOf` (defaults to
  today). It returns `errors`, `messages`, `excess`, `payable`, `lateReport`, `status` and
  `firedRules`, and saves the claim through `IClaimRepository`.
- **Storage:** `Storage:Provider` is `InMemory` by default; `Cosmos` uses `Microsoft.Azure.Cosmos`.
- **Skipped rules:** pending or rejected rules are left out and reported. If an approved rule needs
  a skipped rule's output, generation stops.
- **Repeatable:** offline reruns are byte-identical. `generated/manifest.json` maps each file to the
  rule IDs it implements.
- **Where the method bodies came from:** like the M2 sentences, they were written in the Claude Code
  session from the exact `generate_rule.md` prompts, not by an API call (provider `claude-code` in
  the cache).

## Verify: Parity Court

```bash
fluxora judge 20261108-143433        # exit code 0 only if every case passes
```

What the judge does:

1. **Builds and starts the API.** It runs `dotnet build generated/api`, then starts that build as a
   single process on `127.0.0.1:5080`, and always stops it afterwards. It refuses to run if the port
   is already in use, so it never judges a server it didn't start.
2. **Sends every reference case.** Each case is POSTed with `asOf` set to the case's `today`.
3. **Compares field by field.** Money is compared as exact decimals, and `errors` as a set.
4. **Writes the evidence** to `runs/<run-id>/parity.json`:
   - each case's inputs, expected and actual values, per-field diff and pass/fail, plus the oracle
     that produced the expectation (`powerfx-engine` or `manual`)
   - a per-rule rollup
   - the SHA-256 of `reference-cases.json` before and after the run
   - measured timings

**Blame on failure.** A failing case blames only the rules that own the field that diverged, narrowed
to the rules that actually fired. For example, with R09 broken to `>=`, case R09-02 fails on status,
and only R09 turns red.

### The demo moment: seeded defect and repair

```bash
fluxora judge 20261108-143433 --seed-defect threshold --offline
```

What happens:

1. **The defect is seeded in a copy.** The judge always works on a copy of the code in
   `runs/<run-id>/work/api`, so the committed `generated/` code is never touched. `threshold` changes
   the one `>` in R09's method body to `>=`. If it doesn't find exactly one match, it stops rather than
   guess.
2. **Parity Court goes red** on the £5,000 boundary case (R09-02), and only R09 is blamed.
3. **The repair agent fixes the rule.** It gets the rule, its C# file, the plain-English sentence and the
   failing diffs (`prompts/repair_rule.md`), and replies with the full replacement for that one file.
   The patch is rejected if it:
   - targets any path other than `Rules/<rule>.cs`
   - changes the header, class or method signature
   - special-cases claim or policy IDs

   An accepted patch is applied and the API is rebuilt and re-judged. There are at most 3 attempts per
   rule; after that the rule is `UNRESOLVED`, never PASS, and the exit code is non-zero.
4. **Every attempt goes into `repairs.json`** with its unified diff, build result, judge result and an
   honest mode:

   | mode | source | meaning |
   |---|---|---|
   | `live` | `llm-api` | a real LLM call made in this run |
   | `replay` | `llm-cache` | the committed cached LLM response for this exact prompt |
   | `replay` | `recorded-patch` | `orchestrator/recorded/repair-R09.json`, used only when no LLM answer exists and the file matches the one the patch was recorded against |

   The committed R09 repair was written in the Claude Code session, with no API call. Its provenance
   says so.
5. **Tamper guard.** `reference-cases.json` is hashed before seeding and after the last judgement. Any
   change fails the run and is recorded in `parity.json` under `tamperGuard`.

`parity.json` holds the final verdict plus `seededDefect`, `initial` (the red summary), `repair` and
`tamperGuard`, so the red-to-green story is in one file.

## Layout

```
fixtures/claim-triage/   synthetic Power App export + reference cases
orchestrator/            fluxora CLI and agents (M2+)
oracle/                  Power Fx reference evaluator (M1, optional)
generated/api/           migrated .NET 8 API (M3)
generated/web/           migrated React form (M3)
dashboard/               Transform / Rebuild / Verify views (M6)
runs/<run-id>/           rules.json, parity.json, repairs.json, evidence.md
scripts/                 helper checks
```

## Sample app: claim triage

`fixtures/claim-triage/` is a synthetic export. It is not taken from a real tenant, and all data is fake.

- `app.pa.yaml`: one screen, `ClaimScreen`. Rules R01–R08 are named formulas in `App.Formulas`.
- `flow.json`: the `ClaimTriageFlow` Logic Apps definition, with R10 → R09 → R11 as nested conditions.
- `dataverse-schema.json`: the `Claim` table.
- `reference-cases.json`: expected outputs per case. Status precedence is in `meta.precedence`.

Fixture conventions:

- Money values are decimals. Parse JSON numbers as decimal, never as float.
- Each case carries `inputs.today`. The API will take it as `asOf`, so R03 (`IncidentDate > Today()`) stays deterministic.
- When validation fails, `errors` lists every failing rule ID in order, and the other expected fields are `null`.

Check the fixture:

```bash
python scripts/check_fixture.py
```

## Oracle

The expected values in `reference-cases.json` are checked by Microsoft's open-source Power Fx
engine (`Microsoft.PowerFx.Interpreter` 1.8.1), running the original formulas in `oracle/`:

```bash
dotnet run --project oracle -- fixtures/claim-triage/reference-cases.json
```

It prints every case and field with the hand-written value next to the engine's value. With
`--write`, it labels a case `powerfx-engine` only if the engine produced every field and all of them
matched. If anything differs, it writes nothing and stops, so a person decides which side is wrong.

**Rules the engine evaluates for real:** all eleven, R01 to R11.

- **R01–R08**: evaluated verbatim from the `App.Formulas` block in `app.pa.yaml`.
- **R09, R10**: the flow stores these as Logic Apps expressions, which aren't Power Fx, so the engine runs the Power Fx versions from the CLAUDE.md rule table. R10 uses `TimeUnit.Days`, because the engine rejects the bare `Days` that the table uses.
- **R11 and status precedence**: no single formula in the app holds these, so the oracle encodes the CLAUDE.md order as one Power Fx `If(...)` chain built from the rule formulas.
- **`Today()`**: reads a fixed clock set from each case's `today`.

**Labels:** all 32 cases matched on every field (160 of 160 values), so all are labelled
`powerfx-engine`. None stay `manual`.

**What this does not prove:**
- The precedence chain, the R09/R10 Power Fx versions, and the `errors[]`/`null` output convention are our own encoding. The engine checks the arithmetic and the logic, not whether that encoding is what the business intended.
- The engine runs with decimal numbers, which matches our fixture convention. Canvas Power Apps use floating point.
