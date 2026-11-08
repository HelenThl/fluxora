# Responsible AI note

**Data used.** The sample app is synthetic, with no names or personal data. An LLM only ever sees fixture-derived text:
- formulas, source refs and screen messages
- the rule's sentence and its C# file
- for a repair, the failing cases' rule inputs and the expected-versus-actual values

No claim or policy IDs are sent.

**Privacy and security.** The API key lives in `.env`. It is git-ignored, never printed, and never written to the cache or logs (tested). Without a key, no prompt or data leaves the machine: answers come from the committed cache. With a key, only the prompts above go to the provider. The dashboard server listens on 127.0.0.1 only and accepts approvals from this machine only.

**Human oversight.** A person approves or rejects every extracted rule (dashboard or CLI); decisions are timestamped in `rules.json`. Only approved rules reach the Generator; the rest are skipped and reported. When `fluxora demo` approves automatically it says so, and `--pause` hands the decision back to a person.

**Safeguards.**
- **Narrow LLM role:** the LLM writes wording and single method bodies. Parsing, precedence, comparison and verdicts are deterministic code.
- **Bounded repair:** at most 3 attempts per rule. A patch may replace only `Rules/<rule>.cs`, must keep its signature and may not mention claim or policy IDs.
- **No false passes:** a rule that cannot be fixed is `UNRESOLVED`, never PASS.
- **Tamper guard:** `reference-cases.json` is hashed before and after every run, and any change fails the run.
- **Honest labels:** every LLM answer is labelled live, cached or replay; replays are never shown as live.

**Bias and fairness.** The rules apply the same thresholds to every claim of a given type. Fluxora preserves existing behaviour, including any unfairness already in the original rules. It proves parity, not fairness: a biased rule migrated faithfully still passes.

**Limitations.**
- One synthetic app with 11 rules.
- The parser covers named formulas, `If`/`Switch` status chains and simple flow comparisons, not all of Power Fx. `Notify` and connectors such as e-mail are listed as unsupported.
- All 32 expected results are confirmed by Microsoft's Power Fx engine, but the R09/R10 Power Fx versions and the precedence chain are our own encoding.
- No UI fidelity check and no production data migration.
- The committed LLM answers were written in a Claude Code session; no live API run has been measured.

**FCA and GDPR.** We claim no compliance. A real deployment would still need:
- a DPIA and a lawful basis for processing real claim data
- data-residency and processor terms with the LLM provider
- retention rules for logs and evidence
- named accountability under SM&CR
- Consumer Duty outcome testing, which parity alone cannot provide
