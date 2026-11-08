# AI usage

The submission requires us to declare every AI tool we used. Add one row per AI-assisted step.

| Date | Milestone | Tool | What it produced | What a human changed |
|---|---|---|---|---|
| 2026-11-08 | M0 | Claude Code (Claude Opus 5.5) | Repo scaffold, README stub, synthetic claim-triage fixture (`app.pa.yaml`, `flow.json`, `dataverse-schema.json`), 32 reference cases with hand-computed expected values, `scripts/check_fixture.py` | Pending: a human must check the expected values in `reference-cases.json` against the CLAUDE.md rule table. The LLM drafted them, and CLAUDE.md says the code-generating LLM must not produce reference cases. |
| 2026-11-08 | M1 | Claude Code (Claude Opus 5.5) | `oracle/` .NET 8 console that runs the fixture's Power Fx through `Microsoft.PowerFx.Interpreter` and compares it with `reference-cases.json`. It also wrote the precedence `If(...)` chain and the R09/R10 Power Fx versions, and relabelled all 32 cases `powerfx-engine` after 160/160 values matched. | None yet. The engine now independently agrees with the M0 expected values. A human should still confirm that the precedence chain matches the business rules. |
| 2026-11-08 | M2 | Claude Code (Claude Opus 5.5) | The Extractor (`orchestrator/extract.py`, `llm.py`, `register.py`, `cli.py`), the `extract_rule.md` prompt, `rule-ids.json`, pytest tests, and a fix to three invalid YAML lines in `app.pa.yaml` (label text containing `": "`). | Pending: review the 11 plain-English rule sentences before the demo. |
| 2026-11-08 | M2 | Claude Code (Claude Opus 5.5), in the chat session, with no API call | The 11 plain-English rule sentences and confidence values, written from the exact `extract_rule.md` prompts. They are stored in `orchestrator/cache/` as provider `claude-code`, model `claude-code:claude-opus-5-5`. The live API run was skipped by choice. | Pending review, as above. |
