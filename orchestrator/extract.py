"""Transform: turn a Power App export into a rule register.

Deterministic parsing finds every rule with its source, formula, inputs and output. The LLM writes
only the plain-English sentence and a confidence level for each rule. Anything the parser sees but
cannot map to a rule goes into "unsupported" with a reason. Nothing is dropped silently.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .llm import LLMClient

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "extract_rule.md"
APP_FILE, FLOW_FILE, SCHEMA_FILE, RULE_IDS_FILE = "app.pa.yaml", "flow.json", "dataverse-schema.json", "rule-ids.json"

CONFIDENCE = ("high", "medium", "low")
RULE_KEYS = ("id", "source", "formula", "rule", "inputs", "output", "confidence", "status")

# Behaviour functions we know how to migrate. Anything else called in an On* property is unsupported.
SUPPORTED_APP_FUNCTIONS = {"Set", "If", "Patch", "Defaults", "LookUp", "Choices", "Text"}
SUPPORTED_FLOW_ACTIONS = {"InitializeVariable", "SetVariable", "If", "Response"}
CONDITION_OPERATORS = {"greater": ">", "greaterOrEquals": ">=", "less": "<", "lessOrEquals": "<=", "equals": "="}

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\(")
STRING = re.compile(r'"[^"]*"')


class ExtractError(RuntimeError):
    pass


@dataclass
class Found:
    """A rule the parser found, before it has an ID or a sentence."""

    file: str
    ref: str
    name: str
    formula: str
    inputs: list[str]
    output: str
    context: str


@dataclass
class Extraction:
    register: dict
    warnings: list[str] = field(default_factory=list)
    ignored_properties: int = 0


# --- public entry point ---------------------------------------------------------------------------


def build_register(fixture_dir: Path, client: LLMClient) -> Extraction:
    fixture_dir = Path(fixture_dir)
    for name in (APP_FILE, FLOW_FILE, SCHEMA_FILE, RULE_IDS_FILE):
        if not (fixture_dir / name).is_file():
            raise ExtractError(f"{fixture_dir / name} is missing")

    claim_fields = _claim_fields(fixture_dir / SCHEMA_FILE)
    app = _parse_app(fixture_dir / APP_FILE, claim_fields)
    flow = _parse_flow(fixture_dir / FLOW_FILE)
    found = app.rules + flow.rules

    ids, warnings = _assign_ids(found, fixture_dir / RULE_IDS_FILE)
    by_name = {f.name: ids[_key(f)] for f in found}

    precedence: list[list[str]] = []
    if app.validation:
        precedence.append(sorted(by_name[n] for n in app.validation))
    precedence += [[by_name[n]] for n in app.status_chain]
    if app.status_from_flow:
        precedence += [[by_name[n]] for n in flow.order]

    template = PROMPT_FILE.read_text(encoding="utf-8")
    rules, models = [], set()
    for f in found:
        rule_id = ids[_key(f)]
        entry = client.complete(_render_prompt(template, rule_id, f))
        models.add(entry["model"])
        sentence, confidence = _parse_reply(rule_id, entry["response"])
        rules.append(
            {
                "id": rule_id,
                "source": {"file": f.file, "ref": f.ref},
                "formula": f.formula,
                "rule": sentence,
                "inputs": f.inputs,
                "output": f.output,
                "confidence": confidence,
                "status": "pending",
            }
        )
    rules.sort(key=lambda r: int(r["id"][1:]))

    register = {
        "fixture": fixture_dir.as_posix(),
        "ruleTextModel": ", ".join(sorted(models)),
        "rules": rules,
        "precedence": precedence,
        "unsupported": app.unsupported + flow.unsupported,
        "approvals": [],
    }
    return Extraction(register, warnings, app.ignored_properties)


# --- app.pa.yaml ----------------------------------------------------------------------------------


@dataclass
class _App:
    rules: list[Found]
    validation: list[str]
    status_chain: list[str]
    status_from_flow: bool
    unsupported: list[dict]
    ignored_properties: int


def _parse_app(path: Path, claim_fields: set[str]) -> _App:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    app_props = doc.get("App", {}).get("Properties", {})
    named = _named_formulas(app_props.get("Formulas", ""))
    flows = {n for n, ds in (doc.get("DataSources") or {}).items() if ds.get("Type") == "PowerAutomateFlow"}
    controls = _controls(doc.get("Screens") or {})

    # A named formula that reads a control is an input binding (e.g. ClaimAmount = Value(txtClaimAmount.Text)).
    control_names = [ref.split(".", 1)[1] for ref in controls]
    control_ref = re.compile(r"\b(" + "|".join(map(re.escape, control_names)) + r")\.") if controls else None
    rule_names = [n for n, expr in named.items() if not (control_ref and control_ref.search(expr))]

    # Validation gate: rules that disable the submit button.
    validation: list[str] = []
    for ref, props in controls.items():
        gate = re.match(r"=\s*If\((.*),\s*DisplayMode\.Disabled", str(props.get("DisplayMode", "")), re.S)
        if gate:
            validation += [n for n in _idents(gate.group(1)) if n in rule_names and n not in validation]

    # Error messages: a label whose Visible is exactly a rule name.
    messages = {}
    for props in controls.values():
        visible = str(props.get("Visible", "")).lstrip("=").strip()
        text = re.fullmatch(r'=\s*"([^"]*)"', str(props.get("Text", "")))
        if visible in rule_names and text:
            messages[visible] = text.group(1)

    # Behaviour properties: status chain, flow call, unsupported functions.
    status_chain: list[str] = []
    status_values: dict[str, str] = {}
    status_from_flow = False
    unsupported: list[dict] = []
    # Layout, styling, labels and visibility wiring are not migrated as rules (UI fidelity is out of scope).
    ignored = sum(1 for p in app_props if p != "Formulas")
    for ref, props in controls.items():
        for prop, value in props.items():
            if not prop.startswith("On"):
                ignored += 1
                continue
            formula = str(value).lstrip("=")
            chain = _status_chain(formula)
            if chain:
                pairs, default = chain
                for cond, val in pairs:
                    if cond in rule_names:
                        status_chain.append(cond)
                        status_values[cond] = val
                status_from_flow = _default_is_flow(formula, default, flows)
            seen = set()
            for fn in CALL.findall(STRING.sub('""', formula)):
                is_flow_run = fn.endswith(".Run") and fn[: -len(".Run")] in flows
                if fn in SUPPORTED_APP_FUNCTIONS or is_flow_run or fn in seen:
                    continue
                seen.add(fn)
                unsupported.append(
                    {"file": APP_FILE, "ref": f"{ref}.{prop}", "construct": f"{fn}(...)", "reason": _app_reason(fn)}
                )

    found = []
    for name in rule_names:
        expr = named[name]
        if name in validation:
            output = "Errors"
            message = messages.get(name)
            context = (f"When true, the app shows the message '{message}' and " if message else "When true, ") + (
                "the Submit button is disabled, so the claim cannot be submitted."
            )
        elif name in status_values:
            output = "Status"
            context = f"When true (and no earlier check has applied), Status is set to '{status_values[name]}'."
        else:
            output = name
            context = f"Computes {name} for the claim; the claim screen shows it."
        inputs = [i for i in _idents(expr) if (i in claim_fields or (i in rule_names and i != name))]
        found.append(Found(APP_FILE, f"App.Formulas.{name}", name, expr, inputs, output, context))

    return _App(found, validation, status_chain, status_from_flow, unsupported, ignored)


def _named_formulas(block: str) -> dict[str, str]:
    result = {}
    for part in str(block).lstrip("=").split(";"):
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$", part, re.S)
        if m:
            result[m.group(1)] = m.group(2)
    return result


def _controls(screens: dict) -> dict[str, dict]:
    """Map "Screen.control" to the control's properties, walking nested children."""
    found: dict[str, dict] = {}

    def walk(screen: str, children: list) -> None:
        for child in children or []:
            for name, body in child.items():
                found[f"{screen}.{name}"] = dict(body.get("Properties") or {})
                walk(screen, body.get("Children"))

    for screen, body in screens.items():
        walk(screen, (body or {}).get("Children"))
    return found


def _status_chain(formula: str) -> tuple[list[tuple[str, str]], str] | None:
    """Find Set(var, If(cond, "value", cond, "value", ..., default)) and return its pairs and default."""
    m = re.search(r"Set\(\s*\w+\s*,\s*If\(", formula)
    if not m:
        return None
    args = _split_args(formula, m.end())
    if len(args) < 3 or len(args) % 2 == 0:
        return None
    pairs = []
    for cond, value in zip(args[0:-1:2], args[1:-1:2]):
        literal = re.fullmatch(r'"([^"]*)"', value)
        if not literal:
            return None
        pairs.append((cond, literal.group(1)))
    return pairs, args[-1]


def _default_is_flow(formula: str, default: str, flows: set[str]) -> bool:
    """True when the chain's default is a field of a variable set from a flow's Run(...)."""
    var = default.split(".")[0]
    return any(re.search(rf"Set\(\s*{re.escape(var)}\s*,\s*{re.escape(f)}\.Run\(", formula) for f in flows)


def _split_args(text: str, start: int) -> list[str]:
    """Split the arguments of a call whose '(' ends just before `start`, respecting nesting and strings."""
    args, depth, current, i, in_str = [], 0, [], start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            in_str = ch != '"'
        elif ch == '"':
            in_str = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                args.append("".join(current).strip())
                return args
            depth -= 1
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    return []


def _app_reason(fn: str) -> str:
    if fn == "Notify":
        return (
            "Shows a toast message inside the Power App. It does not change any claim field the rules "
            "compute; the migrated form shows the status returned by the API instead."
        )
    return f"The function {fn} has no mapping in the migrated app yet."


# --- flow.json ------------------------------------------------------------------------------------


@dataclass
class _Flow:
    rules: list[Found]
    order: list[str]
    unsupported: list[dict]


def _parse_flow(path: Path) -> _Flow:
    doc = json.loads(path.read_text(encoding="utf-8"))
    definition = doc.get("properties", {}).get("definition", doc)
    fields: set[str] = set()
    for trigger in definition.get("triggers", {}).values():
        fields |= set(trigger.get("inputs", {}).get("schema", {}).get("properties", {}))

    rules: list[Found] = []
    unsupported: list[dict] = []

    def walk(actions: dict, prefix: str) -> None:
        for name, action in actions.items():
            ref = f"{prefix}{name}"
            kind = action.get("type")
            if kind not in SUPPORTED_FLOW_ACTIONS:
                unsupported.append({"file": FLOW_FILE, "ref": ref, "construct": name, "reason": _flow_reason(action)})
                continue
            if kind != "If":
                continue
            yes = action.get("actions") or {}
            no = (action.get("else") or {}).get("actions") or {}
            try:
                formula = _render(action.get("expression", {}))
            except ValueError as e:
                unsupported.append({"file": FLOW_FILE, "ref": ref, "construct": name, "reason": str(e)})
                walk(yes, f"{ref}.actions.")
                walk(no, f"{ref}.else.actions.")
                continue
            sets = _set_variables(yes)
            rules.append(
                Found(
                    FLOW_FILE,
                    ref,
                    name,
                    formula,
                    [i for i in _idents(formula) if i in fields],
                    ", ".join(v for v, _ in sets),
                    "When true, the flow sets " + _assignments(sets) + ".",
                )
            )
            walk(yes, f"{ref}.actions.")
            defaults = _set_variables(no)
            if defaults and not any(a.get("type") == "If" for a in no.values()):
                first = next(n for n, a in no.items() if a.get("type") == "SetVariable")
                rules.append(
                    Found(
                        FLOW_FILE,
                        f"{ref}.else.actions.{first}",
                        first,
                        "otherwise",
                        [],
                        ", ".join(v for v, _ in defaults),
                        "If none of the flow's earlier conditions applied, the flow sets " + _assignments(defaults) + ".",
                    )
                )
            walk(no, f"{ref}.else.actions.")

    walk(definition.get("actions", {}), "actions.")
    return _Flow(rules, [r.name for r in rules], unsupported)


def _assignments(pairs: list[tuple[str, object]]) -> str:
    def fmt(value: object) -> str:
        return ("true" if value else "false") if isinstance(value, bool) else f"'{value}'"

    return " and ".join(f"{name} = {fmt(value)}" for name, value in pairs)


def _set_variables(actions: dict) -> list[tuple[str, object]]:
    return [
        (a["inputs"]["name"], a["inputs"]["value"]) for a in actions.values() if a.get("type") == "SetVariable"
    ]


def _render(expr: dict) -> str:
    """Render a Logic Apps condition mechanically: greater -> '>', triggerBody()?['X'] -> X."""
    for joiner, word in ((" && ", "and"), (" || ", "or")):
        if word in expr:
            return joiner.join(_render(e) for e in expr[word])
    if "not" in expr:
        return f"Not({_render(expr['not'])})"
    if len(expr) != 1:
        raise ValueError(f"Condition shape not understood: {sorted(expr)}")
    (op, operands), = expr.items()
    if op not in CONDITION_OPERATORS or len(operands) != 2:
        raise ValueError(f"Condition operator '{op}' has no mapping yet.")
    return f"{_operand(operands[0])} {CONDITION_OPERATORS[op]} {_operand(operands[1])}"


def _operand(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text.startswith("@"):
        return json.dumps(text)
    return re.sub(r"triggerBody\(\)\??\['([^']+)'\]", r"\1", text[1:])


def _flow_reason(action: dict) -> str:
    if action.get("type") == "OpenApiConnection":
        host = action.get("inputs", {}).get("host", {})
        api = str(host.get("apiId", "")).rsplit("/", 1)[-1] or "connector"
        return (
            f"Outbound connector call ({api}: {host.get('operationId', 'unknown operation')}). The migrated API "
            "has no mail or connector integration, and the call does not change any claim field the rules compute."
        )
    return f"Flow action type '{action.get('type')}' has no mapping in the migrated app yet."


# --- shared helpers -------------------------------------------------------------------------------


def _claim_fields(path: Path) -> set[str]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return {c["field"] for t in schema.get("tables", []) for c in t.get("columns", []) if "field" in c}


def _idents(expr: str) -> list[str]:
    """Identifiers in order of first appearance, ignoring string literals and function names."""
    cleaned = STRING.sub('""', expr)
    seen: list[str] = []
    for m in IDENT.finditer(cleaned):
        rest = cleaned[m.end():].lstrip()
        if rest.startswith("(") or m.group() in seen:
            continue
        seen.append(m.group())
    return seen


def _key(f: Found) -> str:
    return f"{f.file}#{f.ref}"


def _assign_ids(found: list[Found], ids_path: Path) -> tuple[dict[str, str], list[str]]:
    pinned: dict[str, str] = json.loads(ids_path.read_text(encoding="utf-8"))["ids"]
    keys = {_key(f) for f in found}
    missing = [k for k in pinned if k not in keys]
    if missing:
        raise ExtractError(f"{ids_path.name} names rules the parser did not find: {', '.join(missing)}")

    ids, warnings = {}, []
    next_number = max((int(v[1:]) for v in pinned.values()), default=0) + 1
    for f in found:
        key = _key(f)
        if key in pinned:
            ids[key] = pinned[key]
        else:
            ids[key] = f"R{next_number:02d}"
            warnings.append(f"{key} is not in {ids_path.name}; numbered {ids[key]}")
            next_number += 1
    return ids, warnings


def _render_prompt(template: str, rule_id: str, f: Found) -> str:
    values = {
        "id": rule_id,
        "file": f.file,
        "ref": f.ref,
        "formula": f.formula,
        "inputs": ", ".join(f.inputs) or "(none)",
        "output": f.output,
        "context": f.context,
    }
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def _parse_reply(rule_id: str, text: str) -> tuple[str, str]:
    start, end = text.find("{"), text.rfind("}")
    try:
        reply = json.loads(text[start : end + 1]) if start >= 0 and end > start else None
    except json.JSONDecodeError:
        reply = None
    if not isinstance(reply, dict):
        raise ExtractError(f"The LLM reply for {rule_id} is not a JSON object.")
    sentence, confidence = reply.get("rule"), reply.get("confidence")
    if not isinstance(sentence, str) or not sentence.strip():
        raise ExtractError(f"The LLM reply for {rule_id} has no 'rule' sentence.")
    if confidence not in CONFIDENCE:
        raise ExtractError(f"The LLM reply for {rule_id} has confidence {confidence!r}; expected one of {CONFIDENCE}.")
    return sentence.strip(), confidence
