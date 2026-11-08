# Demo video script (target 2:45, hard limit 2:50)

**Where the numbers come from:**
- Every number below comes from `runs/20261108-160920/evidence.md`, a real `fluxora demo` run.
- The counts are deterministic and will appear on screen exactly as written: 11 rules, 2 unsupported,
  32 cases, 31/32 then 32/32, 1 repair attempt.
- Timings vary from run to run (10.78–15.53s total across the six runs in `docs/measurements.md`).
  For any time, **read the number on screen**.

| Time | On screen | Command / click | Say |
|---|---|---|---|
| 0:00–0:15 | Title slide: "Fluxora: Transform. Rebuild. Verify." | none | "Migrating Power Apps is not the hard part. Proving the new app behaves the same is. Fluxora migrates, then shows you the proof, rule by rule." |
| 0:15–0:25 | Terminal | `fluxora doctor` | "First, a pre-flight check. Dotnet, ports, cache. Ready. Everything runs offline from the repo." |
| 0:25–0:45 | Terminal, stages 1–3 scrolling | `fluxora demo` | "Transform. The extractor finds eleven rules in the app and the flow. Two things it can't migrate, a toast and an e-mail. It lists them instead of dropping them. Here the approval gate is automatic, and it says so. Rebuild. One C# file per approved rule." |
| 0:45–0:55 | Stage 4 line `VERDICT: PASS  32/32 cases, 11/11 rules` | none | "Verify. Thirty-two reference cases, checked by Microsoft's own Power Fx engine. All green." |
| 0:55–1:20 | Stage 5: red Parity Court table, row R09 FAIL, line `R09-02  status: expected "Approved", got "Pending approval"` | Scroll up to the red table | "Now we break it on purpose. One character in rule R09: greater-than becomes greater-or-equal. A claim of exactly five thousand pounds now goes to a manager. Parity Court catches it. One case, one rule, named." |
| 1:20–1:35 | `REPAIR R09 attempt 1/3 [replay: cached LLM response]` and the two-line diff, then `FINAL VERDICT: PASS` | none | "The repair agent may only touch that one rule file. One attempt. One character changed back. Green again. And it says this was a cached answer, not a live call." |
| 1:35–1:45 | `MEASURED TIMINGS` table | none | "The whole pipeline, measured. Total: [read the total on screen; it was 12.11 seconds in the evidence run]. Every stage says whether an LLM was live, cached, or not used." |
| 1:45–2:05 | Browser: Transform view | `fluxora serve <run-id from screen>`, open http://127.0.0.1:8765/ | "The dashboard. Transform: every rule in plain English, with its formula and source. A human approves or rejects each one. Unsupported items are listed with reasons." |
| 2:05–2:15 | Rebuild view, open `R09.cs` | Click **Rebuild**, then **View source** on R09.cs | "Rebuild: every file traces back to a rule ID." |
| 2:15–2:35 | Verify view, **Before repair**, then click **R09-02**, then **After repair** | Click **Verify** → chip **R09-02** → **After repair (PASS)** | "Verify: expected versus actual, field by field, with the oracle on every expectation. Then the repair. Then thirty-two out of thirty-two." |
| 2:35–2:45 | Evidence summary tiles | Scroll down | "Approvals, repairs, unsupported items, a tamper guard on the test cases, all synthetic data. We don't just migrate apps. We show you the proof." |

## Pre-recording checklist

- [ ] Terminal font 20pt or larger, about 120 columns wide; browser window at least 1440px wide, zoom 100–125%.
- [ ] `git status` is clean.
- [ ] `fluxora doctor` says READY. It should show "LLM mode: offline" (no key in `.env`), so every label on screen is honest.
- [ ] Ports 5080 and 8765 are free (doctor checks both).
- [ ] Dashboard built: `cd dashboard && npm install && npm run build`.
- [ ] One warm-up `fluxora demo` beforehand. The first run after a fresh clone is slower (15.53s, against a median of 11.10s), because it does the first .NET build.
- [ ] Note the run ID printed at the end of the recorded run, for `fluxora serve`.
- [ ] Notifications off; no other terminals showing secrets.
