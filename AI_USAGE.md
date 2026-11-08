# AI usage

The submission requires us to declare every AI tool we used. Add one row per AI-assisted step.

| Date | Milestone | Tool | What it produced | What a human changed |
|---|---|---|---|---|
| 2026-11-08 | M0 | Claude Code (Claude Opus 5.5) | Repo scaffold, README stub, synthetic claim-triage fixture (`app.pa.yaml`, `flow.json`, `dataverse-schema.json`), 32 reference cases with hand-computed expected values, `scripts/check_fixture.py` | Pending: a human must check the expected values in `reference-cases.json` against the CLAUDE.md rule table. The LLM drafted them, and CLAUDE.md says the code-generating LLM must not produce reference cases. |
| 2026-11-08 | M1 | Claude Code (Claude Opus 5.5) | `oracle/` .NET 8 console that runs the fixture's Power Fx through `Microsoft.PowerFx.Interpreter` and compares it with `reference-cases.json`. It also wrote the precedence `If(...)` chain and the R09/R10 Power Fx versions, and relabelled all 32 cases `powerfx-engine` after 160/160 values matched. | None yet. The engine now independently agrees with the M0 expected values. A human should still confirm that the precedence chain matches the business rules. |
