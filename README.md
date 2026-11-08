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

> Status: **M0** (scaffold + fixture). Run instructions arrive with M7.

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
