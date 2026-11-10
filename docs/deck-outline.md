# Deck outline (10 slides)

Every figure below is a measured value from a file in this repo. Nothing is estimated. "Evidence run"
means `runs/20261110-175816/evidence.md` (the 8-stage demo); "measurements" means `docs/measurements.md`.

## 1. Fluxora: Transform. Rebuild. Verify.
- Migrates a Power App (Power Fx, a Power Automate flow, Dataverse) to React + .NET 8 + Cosmos DB.
- Then proves the new app behaves the same, rule by rule.
- *"We don't just migrate apps. We show you the proof."*

Evidence: README.

## 2. Problem
- The challenge: about 30 Power Apps to migrate in a 2–3 month window. **☐ Quote the brief's exact wording.**
- Rewriting is not the risk. Silently changing a business rule is.
- Teams need proof per rule that the client can audit, not "it looks the same".

Evidence: challenge brief.

## 3. Approach: three agents, one proof
- **Transform:** code parses every rule; an LLM only writes the plain-English sentence; a human approves each rule.
- **Rebuild:** templates plus one LLM-written method body per approved rule, each file tagged with its rule ID.
- **Rebuild (data):** the Dataverse rows are migrated to Cosmos DB documents; bad rows are quarantined with a reason, and the result is reconciled.
- **Verify:** Parity Court runs the migrated API against reference cases confirmed by Microsoft's Power Fx engine, with a bounded repair loop. The migrated claims are also replayed through the new app.

Evidence: `docs/architecture.mmd`, `orchestrator/`.

## 4. Architecture
- Pipeline diagram, marking where an LLM is called (3 points), the human gate, and the data path (migrate, reconcile, replay).
- Everything else is deterministic code.

Evidence: `docs/architecture.mmd`.

## 5. Results: Transform
- 11 rules extracted with source refs (8 from Power Fx, 3 from the flow); precedence derived from the app.
- 2 unsupported constructs listed with reasons (`Notify`, `Send_an_email`), never dropped.
- 32 reference cases; 32/32 expected results confirmed by the Power Fx engine (160/160 values).

Evidence: evidence run, `README.md` Oracle section.

## 6. Results: Rebuild and Verify
- One C# file per rule; regenerating offline reproduces the committed code byte for byte (checked by `fluxora demo` and the test `test_committed_cache_regenerates_committed_code`).
- Clean code: Parity Court PASS, 32/32 cases, 11/11 rules.
- Seeded defect (`>` to `>=` in R09): FAIL 31/32, only R09 blamed; repaired in 1 attempt; PASS 32/32. The tamper guard showed the reference cases unchanged.

Evidence: evidence run, `parity.json`, `repairs.json`.

## 6b. Results: data migration
- 40 synthetic Dataverse rows: 33 migrated to Cosmos DB documents, 7 quarantined with a reason (duplicate claim ID on 2 rows, unknown option value, missing amount, 3 decimal places, over-long policy number, impossible date). None dropped, none guessed.
- Reconciliation, 7/7 checks: every row accounted for, unique ids, a field-by-field round trip (297 values, 0 differ), money control total £73,488.28 on both sides, counts by type and status, source unchanged.
- Replay: 32/32 migrated claims get the same status from the migrated app as Dataverse stored (1 had no stored status and is listed, not counted).
- The first replay caught a bug in our own synthetic data (two Travel claims over £2,000 stored as Approved without a receipt, which R08 forbids). We fixed the fixture, not the check.

Evidence: evidence run `migration.json`, `migrated-claims.json`.

## 7. Business impact: what we measured
- **Measured:** the full 8-stage pipeline for the sample app took **8.01s** in the evidence run, and **7.86–10.60s** (median 8.01s) across 5 fresh-clone runs.
  - That is 11 rules, 40 Dataverse rows migrated and replayed, 32 cases, a seeded defect and its repair.
  - Machine: one Linux cloud container, offline. An earlier 6-stage set on a Windows 11 machine measured 10.78–15.53s; the two machines differ, so we don't compare them.
- **Not measured:**
  - human review time (the approval gate was auto-approved)
  - live LLM latency (every LLM answer came from the cache)
  - apps larger than 11 rules
- **Comparison:** the brief's 2–3 month window for about 30 apps is calendar time for whole migrations. We show the per-app *agent* time and the proof artefacts, and we do not extrapolate.

Evidence: measurements, evidence run.

## 8. Responsible AI
- Synthetic data only; with no key, no prompt or data leaves the machine; keys are never logged.
- Human approval gate; repair limited to one rule file and 3 attempts; `UNRESOLVED` rather than a false pass; hash guard on reference cases.
- Every LLM answer is labelled live, cached or replay. Fluxora proves parity, not fairness.

Evidence: `docs/responsible-ai.md`.

## 9. Honest limits
- One synthetic app; a Power Fx subset (named formulas, If/Switch chains, simple flow conditions).
- Data migration is shown on 40 synthetic rows, written to a file in Cosmos document shape; no real Dataverse environment or Cosmos account was used. The stored statuses the replay compares against come from our fixture script, not from a run of the original Power App.
- The committed LLM answers were written in a Claude Code session; no live API run has been measured yet.
- Out of scope: UI fidelity, PDF reports, auth, Azure deployment, multi-tenant.

Evidence: README "What is not supported", `AI_USAGE.md`.

## 10. Next steps
- A measured live-LLM run (`.env` + `fluxora demo`), reported next to the cached numbers.
- A second real app export, to grow the parser's Power Fx coverage, with every new rule still checked by the engine.
- Time the human gate with `fluxora demo --pause`, so review effort is measured, not assumed.

Evidence: `fluxora demo --pause`, `fluxora doctor`.
