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

> Status: **M2** (fixture, Power Fx oracle, Extractor). Full run instructions arrive with M7.

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
