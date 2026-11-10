# Demo video script (target 2:45, hard limit 2:50)

**Where the numbers come from:**
- Every number below comes from `runs/20261110-175816/evidence.md`, a real 8-stage `fluxora demo` run.
- The counts are deterministic and will appear on screen exactly as written:
  - 11 rules, 2 unsupported
  - 40 Dataverse rows: 33 migrated, 7 quarantined
  - replay 32/32
  - 32 cases, 31/32 then 32/32
  - 1 repair attempt
- Timings vary from run to run (7.86–10.60s total across the five runs in `docs/measurements.md`).
  For any time, **read the number on screen**.

| Time | On screen | Command / click | Say |
|---|---|---|---|
| 0:00–0:12 | Title slide: "Fluxora: Transform. Rebuild. Verify." | none | "Migrating Power Apps is not the hard part. Proving the new app behaves the same is. Fluxora migrates, then shows you the proof, rule by rule." |
| 0:12–0:20 | Terminal | `fluxora doctor --offline` | "A pre-flight check. Dotnet, ports, cache. Ready. Everything runs offline from the repo." |
| 0:20–0:38 | Terminal, stages 1–3 scrolling | `fluxora demo --offline` | "Transform. The extractor finds eleven rules in the app and the flow. Two things it can't migrate, a toast and an e-mail: listed, not dropped. The approval gate is automatic here, and it says so. Rebuild. One C# file per approved rule." |
| 0:38–0:55 | Stage 4: `QUARANTINED` lines and `MIGRATION: PASS` | none | "Then the data. Forty Dataverse rows become Cosmos DB documents. Seven have problems: a duplicate claim ID, a missing amount, an impossible date. They're quarantined with a reason, never guessed. Every row is accounted for, and the money total matches to the penny." |
| 0:55–1:05 | Stage 5: `32/32 statuses match what Dataverse stored.` and `REPLAY: PASS` | none | "Then we replay the migrated claims through the new app. Thirty-two out of thirty-two get the same status the old system stored." |
| 1:05–1:12 | Stage 6 line `VERDICT: PASS  32/32 cases, 11/11 rules` | none | "Parity Court. Thirty-two reference cases, checked by Microsoft's own Power Fx engine. All green." |
| 1:12–1:32 | Stage 7: red Parity Court table, row R09 FAIL, line `R09-02  status: expected "Approved", got "Pending approval"` | Scroll up to the red table | "Now we break it on purpose. One character in rule R09: greater-than becomes greater-or-equal. A claim of exactly five thousand pounds now goes to a manager. Parity Court catches it. One case, one rule, named." |
| 1:32–1:44 | `REPAIR R09 attempt 1/3 [replay: cached LLM response]`, the two-line diff, `FINAL VERDICT: PASS` | none | "The repair agent may only touch that one rule file. One attempt, one character back, green again. And it says this was a cached answer, not a live call." |
| 1:44–1:52 | `MEASURED TIMINGS` table | none | "The whole pipeline, measured. Total: [read the total on screen; it was 8.01 seconds in the evidence run]. Every stage says whether an LLM was live, cached, or not used." |
| 1:52–2:05 | Browser: Transform view | `fluxora serve <run-id from screen>`, open http://127.0.0.1:8765/ | "The dashboard. Transform: every rule in plain English, with its formula and source. A human approves or rejects each one." |
| 2:05–2:12 | Rebuild view, open `R09.cs` | Click **Rebuild**, then **View source** on R09.cs | "Rebuild: every file traces back to a rule ID." |
| 2:12–2:28 | Verify view, **Before repair**, click **R09-02**, then **After repair** | Click **Verify** → chip **R09-02** → **After repair (PASS)** | "Verify: expected versus actual, field by field, with the oracle on every expectation. Then the repair. Thirty-two out of thirty-two." |
| 2:28–2:45 | Data migration section, then the evidence summary tiles | Scroll down | "The data migration, reconciled and replayed. Approvals, repairs, unsupported items, a tamper guard, all synthetic data. We don't just migrate apps. We show you the proof." |

## Pre-recording checklist

- [ ] Terminal font 20pt or larger, about 120 columns wide; browser window at least 1440px wide, zoom 110–125% (the dashboard uses 14px text).
- [ ] `git status` is clean.
- [ ] The `.env` keeps a live key, so in the recording shell set `LLM_MODEL` to the committed cache's model first (it wins over `.env`):
      bash `export LLM_MODEL=claude-code:claude-opus-5-5`, PowerShell `$env:LLM_MODEL = "claude-code:claude-opus-5-5"`.
      Without this, `--offline` uses the `.env` model and stops at Rebuild with a cache miss.
- [ ] `fluxora doctor --offline` says READY and shows "LLM mode: offline", so every label on screen is honest.
- [ ] Ports 5080 and 8765 are free (doctor checks both). The replay and the judge both use 5080, one after the other.
- [ ] Dashboard built: `cd dashboard && npm install && npm run build`.
- [ ] One warm-up `fluxora demo --offline` beforehand. The first run in a fresh clone was slower in both measurement sets (10.60s against a median of 8.01s in the Linux container; 15.53s against 11.10s on Windows), because it does the first .NET build.
- [ ] Note the run ID printed at the end of the recorded run, for `fluxora serve`.
- [ ] Notifications off; no other terminals showing secrets.
