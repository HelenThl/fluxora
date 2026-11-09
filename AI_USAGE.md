# AI usage declaration

The submission requires us to declare every AI tool we used. This file separates two things:

1. **The tools used to build Fluxora.**
2. **The LLM calls Fluxora makes when it runs.**

Fields marked **☐ TO FILL IN** need the team's own answer. They are left blank on purpose: the commit
history shows no human-authored change. All 14 commits carry the trailer
`Co-Authored-By: Claude Opus 5.5`.

## 1. Tools used to BUILD Fluxora

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic), model **Claude Opus 5.5** (`claude-opus-5-5`), in the Claude desktop app | All code, tests, the synthetic fixture, prompts, templates and docs. It also ran the builds, tests, demos and fresh-clone checks. |
| Microsoft Power Fx engine (`Microsoft.PowerFx.Interpreter` 1.8.1) | **Not AI.** The deterministic oracle that confirmed every expected value in the reference cases (M1). |
| Any other AI tools (slides, video, images, other assistants) | **☐ TO FILL IN** (write "none" if none) |

### What the build assistant produced, per milestone

| Milestone | Commit | Produced by Claude Code |
|---|---|---|
| Preflight | `b5ac28e` | `.gitignore`, `.env.example`, `.claude/settings.json` (which denies Claude Code from reading `.env`) |
| Brief | `44b7c10` | Copied the team's project brief into `CLAUDE.md` |
| M0 | `03e372d` | Repo scaffold; the synthetic fixture (`app.pa.yaml`, `flow.json`, `dataverse-schema.json`); 32 reference cases with hand-computed expected values; `scripts/check_fixture.py` |
| M1 | `c76664f` | `oracle/`, which runs the original Power Fx through Microsoft's engine. All 160 expected values matched, and the 32 cases were relabelled `powerfx-engine`. |
| M2 | `aefc894` | Extractor, LLM client, offline cache, `fluxora extract`/`approve`, tests. Also fixed three invalid YAML lines in the fixture. |
| M3 | `8bbc9e3` | Generator, templates, the generated .NET 8 API, Cosmos model, xUnit tests and React form |
| M4 | `00cde5c` | Judge / Parity Court, rule blame, `parity.json` |
| M5 | `b84ef6e` | Seeded defect, bounded repair loop, tamper guard |
| M6 | `63a3b98` | Dashboard (Transform / Rebuild / Verify), `fluxora serve`, `fluxora evidence` |
| M7 | `e676bf2` | `fluxora demo` with labelled per-stage timings, the README, a fresh-clone check |
| Hardening | `63289ef`, `f5fbb37`, `faadb2d`, `fcbdfbb` | Audit; errors for a missing .NET SDK and a busy port; cache-miss messages; `fluxora doctor` |
| Evidence timings fix | see `git log` ("Keep demo stage timings…") | `fluxora evidence` re-run on its own dropped the demo's per-stage timings; they are now saved to `runs/<id>/timings.json` and reprinted. Run `20261108-160920`'s timings were copied from its own committed evidence.md, not re-measured. Found during an M6 check. |
| Submission pack | `eaf5d57` | `docs/` (architecture, Responsible AI note, measurements, demo script, deck outline) and this file |

### Decisions the team made in the build session

These are not visible in git. **☐ Confirm or correct.**

- Approved the plan for each of M2–M5 before implementation.
- Chose to skip live LLM API calls in M2. Instead, the LLM answers were written in the Claude Code
  session and cached with an honest label (section 2).

### Human review and changes: ☐ TO FILL IN

| Check | Done by / date | Notes |
|---|---|---|
| Spot-checked reference cases against the rule table | ☐ | |
| Read the 11 plain-English rule sentences | ☐ | |
| Confirmed the precedence order matches the business intent | ☐ | |
| Ran the API and the React form by hand | ☐ | |
| Read one `repairs.json` end to end | ☐ | |
| Files a human edited (if any) | ☐ | |

## 2. LLM calls Fluxora makes at RUNTIME

Fluxora calls an LLM at exactly three points. Each answer is cached, keyed by model and prompt, so
reruns are identical.

| Stage | Prompt | The LLM receives | The LLM returns | Guardrails |
|---|---|---|---|---|
| Extractor wording | `orchestrator/prompts/extract_rule.md` | One rule's formula, source ref, inputs, output and on-screen effect | One plain-English sentence and a confidence level | Reply must be valid JSON with a known confidence. ID, source, formula, inputs, output and precedence are parsed by code. |
| Generator rule bodies | `orchestrator/prompts/generate_rule.md` | The rule's sentence, formula, source, the C# signature and its constants | The statements inside one C# method | Declarations are rejected. The code must compile and pass Parity Court. |
| Repair patches | `orchestrator/prompts/repair_rule.md` | The failing rule, its C# file, its formula, and the failing cases' inputs and expected-vs-actual values | The full replacement for that one rule file | Path must be `Rules/<rule>.cs`; signature unchanged; no claim or policy IDs; at most 3 attempts; then `UNRESOLVED`, never PASS |

**Providers:**
- `anthropic`, through the official SDK
- any OpenAI-compatible endpoint, set in `.env`

Without a key, Fluxora makes no calls at all.

**The committed artefacts contain no live API output.** The LLM answers committed in
`orchestrator/cache/` were written by Claude Opus 5.5 inside the Claude Code build session, from the
exact prompts above:
- 11 sentences
- 11 method bodies
- 1 repair patch (also in `orchestrator/recorded/repair-R09.json`)

Every entry says so: provider `claude-code`, model `claude-code:claude-opus-5-5`. Every demo stage
that uses them is labelled "cached LLM" or "replay", never "live LLM". No live API run has been
measured.

## 3. What is NOT LLM-generated at runtime

- **Reference cases** (`fixtures/claim-triage/reference-cases.json`) are a fixed, hash-guarded input
  and are never generated or changed at runtime.
  - They were drafted at build time by Claude Code (M0).
  - Every expected value was then confirmed independently by Microsoft's Power Fx engine (M1,
    160/160 values).
  - The only change since M0 is the M1 relabel of 32 `oracle` labels; no expected value changed.
- **The tamper guard** is deterministic code: a SHA-256 of the reference cases before and after
  every run.
- **Everything else is deterministic code:** parsing, rule IDs, precedence, `Evaluator.cs`, the data
  model, comparison, blame, verdicts, the seeded defect, the evidence page and timings.
