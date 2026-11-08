# Measured demo timings

Every number here was copied from the `evidence.md` that `fluxora demo` wrote for that run. Nothing is estimated.

- **Machine:** Windows 11 Home, Python 3.12.10, .NET SDK 8.0.427.
- **Date:** 2026-11-08.
- **Mode:** offline. Every LLM stage was answered from the committed cache ("cached LLM"), so no live LLM call is included in any timing.
- **Human gate:** auto-approved by the demo. No human review time is included.
- **First run:** the first hardening run was a cold start (first .NET build and restore in a fresh clone).

| Run | Where | Extract | Approve | Generate | Judge clean | Seeded + repair | Evidence | Total |
|---|---|---|---|---|---|---|---|---|
| 20261108-155824 | fresh clone, no .env (hardening) | 0.39 | 0.04 | 0.51 | 7.66 | 6.87 | 0.05 | 15.53 |
| 20261108-155840 | fresh clone, no .env (hardening) | 0.04 | 0.03 | 0.07 | 4.13 | 6.69 | 0.05 | 11.01 |
| 20261108-155851 | fresh clone, no .env (hardening) | 0.04 | 0.04 | 0.08 | 4.05 | 6.93 | 0.03 | 11.19 |
| 20261108-155903 | fresh clone, no .env (hardening) | 0.04 | 0.04 | 0.09 | 3.93 | 6.87 | 0.04 | 11.01 |
| 20261108-155915 | fresh clone, no .env (hardening) | 0.04 | 0.04 | 0.09 | 4.08 | 6.50 | 0.03 | 10.78 |
| 20261108-160920 | main checkout, committed evidence run | 0.05 | 0.03 | 0.07 | 4.41 | 7.49 | 0.06 | 12.11 |

**Spread over all six runs (seconds):**

| Stage | Min | Median | Max | Mode |
|---|---|---|---|---|
| Extract | 0.04 | 0.04 | 0.39 | cached LLM (11 responses, no API calls) |
| Approve | 0.03 | 0.04 | 0.04 | auto-approved, no human (use --pause to approve in the dashboard) |
| Generate | 0.07 | 0.08 | 0.51 | cached LLM (11 responses, no API calls) |
| Judge clean | 3.93 | 4.11 | 7.66 | no LLM (no repair needed) |
| Seeded + repair | 6.50 | 6.87 | 7.49 | repair: cached LLM (1 attempt(s)) |
| Evidence | 0.03 | 0.04 | 0.06 | no LLM |
| Total | 10.78 | 11.10 | 15.53 | - |

The committed evidence run is `runs/20261108-160920/` (its `evidence.md`, `parity.json`, `parity-clean.json` and `repairs.json`).
The five hardening runs were made in a throwaway clone and are not committed. Their figures are reproduced above exactly as their `evidence.md` files recorded them.
