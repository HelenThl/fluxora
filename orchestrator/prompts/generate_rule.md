You are migrating one business rule from a Power Platform app to C# (.NET 8). Write the BODY of the method below: only the C# statements that go between its braces.

- Implement exactly the formula. Do not add checks, thresholds, logging, or comments that change behaviour.
- Use only the parameters given. Money is decimal: write literals with the m suffix, for example 5000m.
- Keep Power Fx semantics. These were checked with Microsoft's Power Fx engine:
  - A blank number (a null decimal? parameter) counts as 0 in arithmetic and in <, <=, > and >=.
  - `=` with a blank number is false, so blank = 0 does not hold.
  - The `in` operator compares text case-insensitively.
  - `=` and Switch compare text exactly, so a case mismatch does not match.
  - Switch with no matching case returns blank (null).
  - Today() is the `today` parameter.
- Logic Apps expressions: ticks() counts 100-nanosecond intervals, 864000000000 ticks is one day, and div() on whole numbers is integer division.
- No using directives, no helper methods, and no class or method declaration.

Reply with the method body only, as plain C# statements. No code fences and no explanation.

Rule: {{id}}
What it does: {{rule}}
Source: {{file}}, {{ref}}
Formula: {{formula}}
Method: {{signature}}
Constants in the class: {{constants}}
