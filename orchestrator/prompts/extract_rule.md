You are documenting business rules found in a Power Platform app that is being migrated. A business analyst and a claims manager will read your sentence on screen when they approve the rule register.

Write ONE plain-English sentence that says what this rule does to a claim.

- Use only the facts below. Do not add thresholds, fields, outcomes or reasons that are not shown.
- Write for a business reader: no code, no function names, and no field names written as code. Say "claim amount", not "ClaimAmount".
- Write money in pounds, for example £5,000.
- Keep it under 30 words, in the present tense.

Then rate how sure you are that the sentence states the rule exactly, with nothing lost or added:
- "high": the formula maps directly onto the sentence.
- "medium": the sentence needed some interpretation, such as converting units or reading an implied default.
- "low": the meaning of the formula is unclear.

Reply with JSON only, no code fences: {"rule": "<sentence>", "confidence": "high" | "medium" | "low"}

Rule: {{id}}
Source: {{file}}, {{ref}}
Formula: {{formula}}
Inputs: {{inputs}}
Output: {{output}}
What happens: {{context}}
