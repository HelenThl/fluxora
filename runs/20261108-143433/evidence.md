# Fluxora evidence: run 20261108-143433

**Transform. Rebuild. Verify.**

Written 2026-11-08T15:13:02Z by `fluxora evidence 20261108-143433`, from `runs/20261108-143433/`.

## Summary

- **Transform:** 11 rules extracted from `fixtures/claim-triage`. 11 approved, 0 rejected, 0 pending (11 timestamped decisions). 2 unsupported constructs are listed below.
- **Rebuild:** 30 files generated under `generated/`, including 11 rule files, each traceable to one rule ID.
- **Verify:** Parity Court **PASS**: 32/32 cases and 11/11 rules. Seeded defect `threshold` in R09 made the first verdict FAIL (31/32 cases; red: R09).
- **Repair:** 1 attempt(s); fixed R09; unresolved -.
- **Tamper guard:** reference cases unchanged (sha256 `b275b239cd3e316d`).

## Rule register

| ID | Rule | Formula | Source | Confidence | Status | Decided |
|---|---|---|---|---|---|---|
| R01 | A claim cannot be submitted if the claim amount is missing, zero or negative; the form shows 'Amount must be greater than zero'. | `IsBlank(ClaimAmount) \|\| ClaimAmount <= 0` | app.pa.yaml `App.Formulas.AmountInvalid` | high | approved | 2026-11-08T14:34:43Z |
| R02 | A claim cannot be submitted unless its claim type is Motor, Home or Travel. | `Not(ClaimType in ["Motor","Home","Travel"])` | app.pa.yaml `App.Formulas.ClaimTypeInvalid` | high | approved | 2026-11-08T14:34:43Z |
| R03 | A claim cannot be submitted if the incident date is later than today. | `IncidentDate > Today()` | app.pa.yaml `App.Formulas.IncidentInFuture` | high | approved | 2026-11-08T14:34:43Z |
| R04 | If the incident happened before the policy start date, the claim's status is set to Not covered. | `IncidentDate < PolicyStartDate` | app.pa.yaml `App.Formulas.NotCovered` | high | approved | 2026-11-08T14:34:43Z |
| R05 | The excess is £250 for Motor claims, £350 for Home claims and £100 for Travel claims. | `Switch(ClaimType,"Motor",250,"Home",350,"Travel",100)` | app.pa.yaml `App.Formulas.Excess` | high | approved | 2026-11-08T14:34:43Z |
| R06 | The payable amount is the claim amount minus the excess, and never less than £0. | `Max(0, ClaimAmount - Excess)` | app.pa.yaml `App.Formulas.Payable` | high | approved | 2026-11-08T14:34:43Z |
| R07 | If the payable amount is £0, the claim's status is set to Below excess. | `Payable = 0` | app.pa.yaml `App.Formulas.BelowExcess` | high | approved | 2026-11-08T14:34:43Z |
| R08 | A Travel claim over £2,000 cannot be submitted without a receipt. | `ClaimType = "Travel" && ClaimAmount > 2000 && !HasReceipt` | app.pa.yaml `App.Formulas.ReceiptMissing` | high | approved | 2026-11-08T14:34:43Z |
| R09 | If the claim amount is over £5,000, the claim's status is set to Pending approval. | `ClaimAmount > 5000` | flow.json `actions.Condition_LateReport.else.actions.Condition_Amount` | high | approved | 2026-11-08T14:34:43Z |
| R10 | If the claim is reported more than 30 days after the incident, it is flagged as a late report and its status is set to Manual review. | `div(sub(ticks(ReportedDate), ticks(IncidentDate)), 864000000000) > 30` | flow.json `actions.Condition_LateReport` | medium | approved | 2026-11-08T14:34:43Z |
| R11 | If none of the flow's earlier checks apply, the claim's status is set to Approved. | `otherwise` | flow.json `actions.Condition_LateReport.else.actions.Condition_Amount.else.actions.Set_Status_Approved` | high | approved | 2026-11-08T14:34:43Z |

## Parity Court

| Rule | Cases | Verdict | Oracle |
|---|---|---|---|
| R01 | 4/4 | PASS | powerfx-engine |
| R02 | 3/3 | PASS | powerfx-engine |
| R03 | 4/4 | PASS | powerfx-engine |
| R04 | 3/3 | PASS | powerfx-engine |
| R05 | 24/24 | PASS | powerfx-engine |
| R06 | 24/24 | PASS | powerfx-engine |
| R07 | 5/5 | PASS | powerfx-engine |
| R08 | 5/5 | PASS | powerfx-engine |
| R09 | 5/5 | PASS | powerfx-engine |
| R10 | 5/5 | PASS | powerfx-engine |
| R11 | 15/15 | PASS | powerfx-engine |

**Failing cases (initial verdict):**

- R09-02 (rules R09): status expected `"Approved"`, got `"Pending approval"` [oracle: powerfx-engine]

## Repair log

### Attempt 1: R09 (replay, llm-cache): fixed

Provenance: provider `claude-code`, model `claude-code:claude-opus-5-5`. Claude Opus 5.5 in a Claude Code session; written in chat from the prompt, no API call

Build ok; judge PASS (32/32 cases).

```diff
--- a/Rules/R09.cs
+++ b/Rules/R09.cs
@@ -16,3 +16,3 @@
     {
-        return (claimAmount ?? 0m) >= 5000m;
+        return (claimAmount ?? 0m) > 5000m;
     }
```


## Unsupported items

| File | Ref | Construct | Reason |
|---|---|---|---|
| app.pa.yaml | `ClaimScreen.btnSubmit.OnSelect` | `Notify(...)` | Shows a toast message inside the Power App. It does not change any claim field the rules compute; the migrated form shows the status returned by the API instead. |
| flow.json | `actions.Condition_LateReport.else.actions.Condition_Amount.actions.Send_an_email` | `Send_an_email` | Outbound connector call (shared_office365: SendEmailV2). The migrated API has no mail or connector integration, and the call does not change any claim field the rules compute. |

## Oracle coverage

| Oracle | Cases |
|---|---|
| powerfx-engine | 32 |

## Timings (measured wall-clock)

Last judge pass: build 4.2s, API start 1.2s, cases 0.62s.

## Data notes

- All data is synthetic: no real names, policy numbers or personal data anywhere in the fixture.
- 32 of 32 expected results were confirmed by Microsoft's Power Fx engine; 0 rely on hand-written values.
- Rule sentences were written in a Claude Code session from the extractor's prompts, not by a live API call.
- C# rule bodies were written in a Claude Code session from the generator's prompts, not by a live API call.
- Repair attempt 1 for R09 was a replay (llm-cache), not a live LLM call.
