# Measured demo timings

Every number here was copied from the `evidence.md` (or `timings.json`) that `fluxora demo` wrote for that run. Nothing is estimated.

## Current demo: 8 stages, with data migration and replay (2026-11-10)

- **Machine:** Linux cloud container (Ubuntu 24.04), Python 3.13.18, .NET SDK 8.0.133.
- **Where:** a fresh clone from GitHub (`claude/awesome-cannon-0mpfpp` at `75bce2a`), set up only with the README steps, no `.env`. Five `fluxora demo` runs back to back.
- **Mode:** offline. Every LLM stage was answered from the committed cache, so no live LLM call is included in any timing.
- **Human gate:** auto-approved by the demo. No human review time is included.
- **Caveat:** NuGet packages were already in this machine's cache, so the first run did not download any. It still did the clone's first .NET build.
- **Rounding:** the demo prints two decimals; `0.00` means under 5 milliseconds.

| Run | Extract | Approve | Generate | Migrate | Replay | Judge clean | Seeded + repair | Evidence | Total |
|---|---|---|---|---|---|---|---|---|---|
| 20261110-175740 (first in the clone) | 0.01 | 0.00 | 0.02 | 0.00 | 2.20 | 4.33 | 4.02 | 0.00 | 10.60 |
| 20261110-175751 | 0.01 | 0.00 | 0.02 | 0.00 | 2.25 | 2.20 | 4.13 | 0.00 | 8.62 |
| 20261110-175800 | 0.01 | 0.00 | 0.02 | 0.00 | 2.22 | 2.17 | 3.44 | 0.00 | 7.86 |
| 20261110-175808 | 0.01 | 0.00 | 0.02 | 0.00 | 2.00 | 2.11 | 3.78 | 0.00 | 7.92 |
| 20261110-175816 (committed evidence run) | 0.01 | 0.00 | 0.02 | 0.00 | 2.26 | 2.04 | 3.68 | 0.00 | 8.01 |

**Spread over the five runs (seconds):**

| Stage | Min | Median | Max | Mode |
|---|---|---|---|---|
| Transform: extract | 0.01 | 0.01 | 0.01 | cached LLM (11 responses, no API calls) |
| Transform: approval gate | 0.00 | 0.00 | 0.00 | auto-approved, no human |
| Rebuild: generate | 0.02 | 0.02 | 0.02 | cached LLM (11 responses, no API calls) |
| Rebuild: migrate data | 0.00 | 0.00 | 0.00 | no LLM (40 rows: 33 migrated, 7 quarantined) |
| Verify: replay migrated data | 2.00 | 2.22 | 2.26 | no LLM (includes this run's first .NET build) |
| Verify: judge clean code | 2.04 | 2.17 | 4.33 | no LLM (no repair needed) |
| Verify: seeded defect + repair | 3.44 | 3.78 | 4.13 | repair: cached LLM (1 attempt) |
| Evidence | 0.00 | 0.00 | 0.00 | no LLM |
| Total | 7.86 | 8.01 | 10.60 | - |

The committed evidence run is `runs/20261110-175816/`, the run with the median total. It holds `evidence.md`, `parity.json`, `parity-clean.json`, `repairs.json`, `migration.json` and `migrated-claims.json`. The other four runs were made in the throwaway clone and are not committed; their figures are reproduced above exactly as their `timings.json` files recorded them.

These numbers come from a different machine than the earlier set below, so the two sets are not a like-for-like comparison.

## Earlier: 6-stage demo, before data migration (2026-11-08)

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

The committed evidence run for this earlier set is `runs/20261108-160920/` (its `evidence.md`, `parity.json`, `parity-clean.json` and `repairs.json`).
The five hardening runs were made in a throwaway clone and are not committed. Their figures are reproduced above exactly as their `evidence.md` files recorded them.
