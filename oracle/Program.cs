// Fluxora oracle (M1). Evaluates the ORIGINAL Power Fx formulas from the claim-triage fixture with
// Microsoft's Power Fx interpreter and compares the results with the expectations in
// reference-cases.json.
//
//   dotnet run --project oracle -- fixtures/claim-triage/reference-cases.json [--write]
//
// --write labels a case "powerfx-engine" only when the engine produced every expected field and
// all of them matched. If any case mismatches, nothing is written: a human decides which is right.

using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.PowerFx;
using Microsoft.PowerFx.Functions;
using Microsoft.PowerFx.Types;

var positional = args.Where(a => !a.StartsWith("--")).ToList();
var write = args.Contains("--write");
if (positional.Count != 1)
{
    Console.Error.WriteLine("usage: dotnet run --project oracle -- <reference-cases.json> [--write]");
    return 2;
}

var casesPath = Path.GetFullPath(positional[0]);
var fixtureDir = Path.GetDirectoryName(casesPath)!;
var appPath = Path.Combine(fixtureDir, "app.pa.yaml");

// --- 1. Formulas -------------------------------------------------------------------------------

// Named formulas from App.Formulas in app.pa.yaml, exactly as written in the fixture.
var named = ReadNamedFormulas(File.ReadAllText(appPath));

// The six input formulas bind controls (e.g. ClaimAmount = Value(txtClaimAmount.Text)).
// The oracle replaces them with the case inputs.
string[] inputNames = ["ClaimAmount", "ClaimType", "PolicyStartDate", "IncidentDate", "ReportedDate", "HasReceipt"];

// Rule formulas taken from the app, in dependency order (Excess before Payable before BelowExcess).
(string Rule, string Name)[] appRules =
[
    ("R01", "AmountInvalid"),
    ("R02", "ClaimTypeInvalid"),
    ("R03", "IncidentInFuture"),
    ("R04", "NotCovered"),
    ("R05", "Excess"),
    ("R06", "Payable"),
    ("R07", "BelowExcess"),
    ("R08", "ReceiptMissing"),
];

var missing = inputNames.Concat(appRules.Select(r => r.Name)).Where(n => !named.ContainsKey(n)).ToList();
if (missing.Count > 0)
{
    Console.Error.WriteLine($"app.pa.yaml is missing named formulas: {string.Join(", ", missing)}");
    return 2;
}

// R09 and R10 live in flow.json as Logic Apps expressions, which are not Power Fx. The engine
// evaluates the Power Fx rendering of those conditions from the CLAUDE.md rule table instead.
// The table writes R10 with a bare `Days`; the interpreter rejects that ("'Days' isn't
// recognized"), so the unit is spelled TimeUnit.Days here. The meaning is the same.
(string Rule, string Name, string Formula)[] flowRules =
[
    ("R09", "PendingApproval", "ClaimAmount > 5000"),
    ("R10", "LateReport", "DateDiff(IncidentDate, ReportedDate, TimeUnit.Days) > 30"),
];

// Status precedence is not a single formula in the app or the flow. This If(...) chain is OUR
// encoding of the CLAUDE.md precedence (validation -> R04 -> R07 -> R10 -> R09 -> R11), built only
// from the rule formulas above. R11 is the final "otherwise" branch.
const string StatusChain = """
    If(
        AmountInvalid || ClaimTypeInvalid || IncidentInFuture || ReceiptMissing, Blank(),
        NotCovered, "Not covered",
        BelowExcess, "Below excess",
        LateReport, "Manual review",
        PendingApproval, "Pending approval",
        "Approved"
    )
    """;

var steps = appRules.Select(r => (r.Rule, r.Name, Formula: named[r.Name]))
    .Concat(flowRules)
    .Append(("R11", "Status", StatusChain))
    .ToList();

Console.WriteLine("Formulas evaluated by Microsoft.PowerFx.Interpreter");
foreach (var (rule, name, formula) in steps)
{
    var source = rule switch { "R09" or "R10" => "CLAUDE.md rendering of flow.json", "R11" => "oracle precedence chain", _ => "app.pa.yaml App.Formulas" };
    Console.WriteLine($"  {rule}  {name,-16} {source,-34} {OneLine(formula)}");
}
Console.WriteLine();

// --- 2. Evaluate every case --------------------------------------------------------------------

using var doc = JsonDocument.Parse(File.ReadAllText(casesPath));
var cases = doc.RootElement.GetProperty("cases").EnumerateArray().ToList();
string[] fields = ["errors", "excess", "payable", "lateReport", "status"];
(string Rule, string Name)[] validation = [("R01", "AmountInvalid"), ("R02", "ClaimTypeInvalid"), ("R03", "IncidentInFuture"), ("R08", "ReceiptMissing")];

var config = new PowerFxConfig();
var rows = new List<(string Case, string Field, string Expected, string Engine, string Result)>();
var engineCases = new List<string>();
var mismatchCases = new List<string>();

foreach (var c in cases)
{
    var id = c.GetProperty("id").GetString()!;
    var inputs = c.GetProperty("inputs");
    var expected = c.GetProperty("expected");

    var engine = new RecalcEngine(config);
    engine.UpdateVariable("ClaimAmount", Money(inputs.GetProperty("claimAmount")));
    engine.UpdateVariable("ClaimType", Text(inputs.GetProperty("claimType")));
    engine.UpdateVariable("PolicyStartDate", Date(inputs.GetProperty("policyStartDate")));
    engine.UpdateVariable("IncidentDate", Date(inputs.GetProperty("incidentDate")));
    engine.UpdateVariable("ReportedDate", Date(inputs.GetProperty("reportedDate")));
    engine.UpdateVariable("HasReceipt", FormulaValue.New(inputs.GetProperty("hasReceipt").GetBoolean()));

    // Today() reads this fixed clock, so R03 uses the case's "today" and stays deterministic.
    var today = DateOnly.ParseExact(inputs.GetProperty("today").GetString()!, "yyyy-MM-dd", CultureInfo.InvariantCulture);
    var runtime = new RuntimeConfig();
    runtime.SetTimeZone(TimeZoneInfo.Utc);
    runtime.SetClock(new FixedClock(today.ToDateTime(new TimeOnly(12, 0), DateTimeKind.Utc)));

    var values = new Dictionary<string, FormulaValue>();
    foreach (var (_, name, formula) in steps)
    {
        FormulaValue value;
        try
        {
            value = await engine.EvalAsync(formula, CancellationToken.None, runtimeConfig: runtime);
        }
        catch (Exception ex)
        {
            value = FormulaValue.NewError(new ExpressionError { Message = ex.Message });
        }
        values[name] = value;
        engine.UpdateVariable(name, value);
    }

    // errors[] collects the failing validation rules in rule order; when any fail, the other
    // fields are null (fixture convention in reference-cases.json meta.conventions).
    var engineOut = new Dictionary<string, Out>();
    var validationResults = validation.Select(v => (v.Rule, Value: AsBool(values[v.Name]))).ToList();
    if (validationResults.Any(v => v.Value is null))
    {
        engineOut["errors"] = Out.Fail(string.Join("; ", validation.Select(v => $"{v.Rule}: {Describe(values[v.Name])}")));
    }
    else
    {
        var errors = validationResults.Where(v => v.Value == true).Select(v => v.Rule).ToList();
        engineOut["errors"] = Out.Ok("[" + string.Join(",", errors) + "]");
        if (errors.Count > 0)
        {
            foreach (var f in fields.Skip(1)) engineOut[f] = Out.Ok("null");
        }
        else
        {
            engineOut["excess"] = AsMoney(values["Excess"]);
            engineOut["payable"] = AsMoney(values["Payable"]);
            engineOut["lateReport"] = AsBool(values["LateReport"]) is bool late ? Out.Ok(late ? "true" : "false") : Out.Fail(Describe(values["LateReport"]));
            engineOut["status"] = values["Status"] switch
            {
                StringValue s => Out.Ok(s.Value),
                BlankValue => Out.Ok("null"),
                var other => Out.Fail(Describe(other)),
            };
        }
    }

    var allProduced = true;
    var allMatch = true;
    foreach (var f in fields)
    {
        var exp = Canonical(expected.GetProperty(f));
        var got = engineOut[f];
        var result = !got.Produced ? "NO VALUE" : got.Text == exp ? "match" : "MISMATCH";
        allProduced &= got.Produced;
        allMatch &= result == "match";
        rows.Add((id, f, exp, got.Text, result));
    }
    if (allProduced && allMatch) engineCases.Add(id);
    if (rows.Any(r => r.Case == id && r.Result == "MISMATCH")) mismatchCases.Add(id);
}

// --- 3. Report ---------------------------------------------------------------------------------

Console.WriteLine($"{"case",-8} {"field",-11} {"manual expected",-18} {"engine value",-18} result");
Console.WriteLine(new string('-', 70));
foreach (var r in rows)
{
    Console.WriteLine($"{r.Case,-8} {r.Field,-11} {r.Expected,-18} {r.Engine,-18} {r.Result}");
}
Console.WriteLine();
Console.WriteLine($"Cases where the engine produced and matched every field: {engineCases.Count}/{cases.Count}");

if (mismatchCases.Count > 0)
{
    Console.WriteLine($"MISMATCH in: {string.Join(", ", mismatchCases)}");
    Console.WriteLine("Nothing written. A human must decide whether the expectation or the formula is wrong.");
    return 1;
}

var notEngine = cases.Select(c => c.GetProperty("id").GetString()!).Except(engineCases).ToList();
if (notEngine.Count > 0) Console.WriteLine($"Stay manual (engine did not produce every field): {string.Join(", ", notEngine)}");

if (write)
{
    var text = File.ReadAllText(casesPath);
    foreach (var id in engineCases) text = Relabel(text, id);
    File.WriteAllText(casesPath, text);
    Console.WriteLine($"Wrote \"oracle\": \"powerfx-engine\" on {engineCases.Count} case(s) in {Path.GetFileName(casesPath)}.");
}
return 0;

// --- helpers -----------------------------------------------------------------------------------

static Dictionary<string, string> ReadNamedFormulas(string yaml)
{
    // Take the indented block under "Formulas: |-" and split it into "Name = formula" pairs.
    var lines = yaml.Replace("\r\n", "\n").Split('\n');
    var start = Array.FindIndex(lines, l => l.TrimStart().StartsWith("Formulas:"));
    if (start < 0) throw new InvalidOperationException("No Formulas block in app.pa.yaml");
    var indent = lines[start].Length - lines[start].TrimStart().Length;
    var block = lines.Skip(start + 1)
        .TakeWhile(l => l.Trim().Length == 0 || l.Length - l.TrimStart().Length > indent)
        .Select(l => l.Trim());
    var body = string.Join("\n", block).TrimStart('=');

    var result = new Dictionary<string, string>();
    foreach (var part in body.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
    {
        var m = Regex.Match(part, @"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", RegexOptions.Singleline);
        if (m.Success) result[m.Groups[1].Value] = m.Groups[2].Value.Trim();
    }
    return result;
}

static FormulaValue Money(JsonElement e) =>
    e.ValueKind == JsonValueKind.Null ? FormulaValue.NewBlank(FormulaType.Decimal) : FormulaValue.New(e.GetDecimal());

static FormulaValue Text(JsonElement e) =>
    e.ValueKind == JsonValueKind.Null ? FormulaValue.NewBlank(FormulaType.String) : FormulaValue.New(e.GetString()!);

static FormulaValue Date(JsonElement e) =>
    FormulaValue.NewDateOnly(DateTime.ParseExact(e.GetString()!, "yyyy-MM-dd", CultureInfo.InvariantCulture));

static bool? AsBool(FormulaValue v) => v is BooleanValue b ? b.Value : null;

static Out AsMoney(FormulaValue v) => v switch
{
    DecimalValue d => Out.Ok(d.Value.ToString("0.00", CultureInfo.InvariantCulture)),
    NumberValue n => Out.Ok(((decimal)n.Value).ToString("0.00", CultureInfo.InvariantCulture) + " (float)"),
    _ => Out.Fail(Describe(v)),
};

static string Canonical(JsonElement e) => e.ValueKind switch
{
    JsonValueKind.Null => "null",
    JsonValueKind.True => "true",
    JsonValueKind.False => "false",
    JsonValueKind.Number => e.GetDecimal().ToString("0.00", CultureInfo.InvariantCulture),
    JsonValueKind.String => e.GetString()!,
    JsonValueKind.Array => "[" + string.Join(",", e.EnumerateArray().Select(x => x.GetString())) + "]",
    _ => e.GetRawText(),
};

static string Describe(FormulaValue v) => v switch
{
    ErrorValue err => "error: " + string.Join("; ", err.Errors.Select(x => x.Message)),
    BlankValue => "blank",
    _ => $"{v.GetType().Name}",
};

static string OneLine(string s) => Regex.Replace(s, @"\s+", " ").Trim();

static string Relabel(string text, string id)
{
    // Change only this case's "oracle" value, keeping the file's formatting as it is.
    var at = text.IndexOf($"\"id\": \"{id}\"", StringComparison.Ordinal);
    var next = text.IndexOf("\"id\": \"", at + 1, StringComparison.Ordinal);
    var end = next < 0 ? text.Length : next;
    const string from = "\"oracle\": \"manual\"";
    var pos = text.IndexOf(from, at, end - at, StringComparison.Ordinal);
    if (at < 0 || pos < 0) throw new InvalidOperationException($"Could not find the oracle field for case {id}");
    return text[..pos] + "\"oracle\": \"powerfx-engine\"" + text[(pos + from.Length)..];
}

sealed record Out(bool Produced, string Text)
{
    public static Out Ok(string text) => new(true, text);
    public static Out Fail(string why) => new(false, why);
}

sealed class FixedClock(DateTime utcNow) : IClockService
{
    public DateTime UtcNow => utcNow;
}
