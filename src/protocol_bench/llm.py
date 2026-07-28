"""Turn each benchmark task into a prompt a language model can attempt, and score what comes back.

The benchmark's harder and more interesting question is not "can a model checker do this" — it can,
exhaustively — but **can a language model produce a verdict AND a counterexample that replays**.
Predicting "violated" is a coin flip on a two-class problem. Producing a trace that starts at the
initial state, moves only along real transitions, and ends in a genuinely violating state is not.

Two modes, deliberately different in difficulty:

``model``
    The full state machine is rendered into the prompt: fields, initial state, and the complete
    transition table. No protocol knowledge is required; this measures formal reasoning alone.

``spec``
    Only the standards clause, the procedure's description, and the property. The model must know
    (or infer) how the procedure actually behaves. This is the hard mode, and it is the one that
    corresponds to what a security researcher does.

Nothing here calls a model or requires a network. You supply the completions; this module builds
the prompts and scores the replies.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from minicheck._core import _reachable

from .score import score
from .tasks import Task, load_tasks

MODES = ("model", "spec")

_RESPONSE_CONTRACT = """\
Answer with a single JSON object and nothing else:

{
  "violated": true | false,
  "trace": [ {"state": {<field>: <value>, ...}}, ... ]
}

Rules for "trace" (omit it entirely if "violated" is false):
  * Include it ONLY if you claim the property is violated.
  * The first entry MUST be the initial state exactly as given.
  * Each consecutive pair MUST be a transition that appears in the model.
  * The final state MUST make the property false.
A trace that does not replay against the model earns no credit, so an honest
"violated": false is worth more than a violation you cannot demonstrate."""


def render_model(task: Task, max_states: int = 200) -> str:
    """Render the state machine as text: fields, initial state, full transition table."""
    m = task.build()
    parent, order = _reachable(m)
    lines = [
        f"State fields (in order): {', '.join(m.fields)}",
        f"Initial state: {dict(zip(m.fields, m.initial))}",
        "",
        "Transitions (from-state -- label --> to-state):",
    ]
    shown = 0
    for s in order:
        succ = m.transitions(s)
        if not succ:
            lines.append(f"  {dict(zip(m.fields, s))}  (no outgoing transitions)")
        for label, ns in succ:
            lines.append(f"  {dict(zip(m.fields, s))}  --{label}-->  {dict(zip(m.fields, ns))}")
        shown += 1
        if shown >= max_states:
            lines.append(f"  ... ({len(order) - shown} further states omitted)")
            break
    return "\n".join(lines)


def _docstring(task: Task) -> str:
    fn = getattr(getattr(__import__("protocol_bench.models", fromlist=[task.module]), task.module), task.builder)
    doc = (fn.__doc__ or "").strip()
    return re.sub(r"\s*\n\s*", " ", doc)


def build_prompt(task: Task, mode: str = "model") -> str:
    """The full prompt for one task. `mode` is 'model' or 'spec'."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")

    head = (
        "You are analysing a published communication-protocol procedure for a safety violation.\n\n"
        f"Standards body: {task.standards_body}\n"
        f"Specification clause: {task.spec_clause}\n"
        f"Safety property that must hold: {task.property}\n"
    )

    if mode == "model":
        body = (
            "\nThe procedure is given below as a finite state machine. The property must hold in "
            "EVERY state reachable from the initial state.\n\n"
            f"{render_model(task)}\n\n"
            f"The property {task.property!r} is FALSE exactly when the state makes it false; infer "
            "its meaning from the field names.\n"
        )
    else:
        body = (
            "\nYou are given only the specification reference and a description of the procedure. "
            "No state machine is provided; reason from how this procedure actually behaves.\n\n"
            f"Procedure: {_docstring(task)}\n\n"
            "If you claim a violation, express your trace using the state fields named in that "
            "description.\n"
        )

    return f"{head}{body}\n{_RESPONSE_CONTRACT}"


def build_prompts(mode: str = "model", tasks: Optional[list[Task]] = None) -> dict[str, str]:
    """Every task's prompt, keyed by task id."""
    return {t.id: build_prompt(t, mode) for t in (tasks or load_tasks())}


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _balanced_spans(text: str):
    """Yield ``(start, end)`` for each brace-balanced region, in one left-to-right pass.

    Tracks string and escape state so a ``{`` inside a JSON string does not open a region. Every
    character is visited exactly once, so this is O(len(text)) regardless of how adversarial the
    input is — which matters, because the text is a language model's reply and nothing constrains
    its shape.
    """
    depth = 0
    start = -1
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield start, i + 1
                    start = -1


def _json_objects(text: str):
    """Yield every JSON object embedded in `text`, left to right.

    The previous implementation tried every (start, end) substring pair and called `json.loads` on
    each, which is cubic in the length of the reply: a brace-heavy 3.2 KB input took 4.4 seconds and
    a 50 KB model reply stalled scoring for minutes. This scans once for balanced regions and parses
    each candidate at most once.
    """
    for start, end in _balanced_spans(text):
        try:
            obj = json.loads(text[start:end])
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def parse_response(text: str) -> dict:
    """Extract a prediction from a model's reply, tolerantly.

    Handles a bare JSON object, a fenced code block, or JSON with prose around it. A reply that
    cannot be parsed is scored as `violated: false` **with ``parse_error: True``** — an unreadable
    answer is not a detection, and the flag keeps that distinct from a model that actually looked
    and found nothing. `score_completions` surfaces the count, so a run where the parser silently
    ate every reply cannot masquerade as a run where the model was simply cautious.
    """
    if isinstance(text, dict):
        raw = text
    else:
        raw = None
        # An object we care about must contain the key, so the key must appear in the raw text.
        # This one O(n) substring check short-circuits the pathological case (a reply that is all
        # opening braces and no JSON), where the scan below would otherwise attempt a decode at
        # every brace: 100 KB of "{{{{..." goes from ~0.7s to ~0.001s.
        if '"violated"' not in (text or ""):
            return {"violated": False, "trace": None, "parse_error": True}
        # Fenced blocks first (the model was explicit), then the whole reply.
        for chunk in [*_FENCE.findall(text or ""), text or ""]:
            for obj in _json_objects(chunk):
                if "violated" in obj:
                    raw = obj
                    break
            if raw is not None:
                break
        if raw is None:
            return {"violated": False, "trace": None, "parse_error": True}

    out = {"violated": bool(raw.get("violated", False)), "parse_error": False}
    tr = raw.get("trace")
    out["trace"] = tr if isinstance(tr, list) else None
    return out


def score_completions(completions: dict, tasks: Optional[list[Task]] = None) -> dict:
    """Score raw model replies (task id -> completion text or dict).

    Adds `n_unparseable` to the usual report so a model that answers in prose is distinguishable
    from one that answers "safe".
    """
    tasks = tasks or load_tasks()
    submission, unparseable = {}, 0
    for t in tasks:
        parsed = parse_response(completions.get(t.id, ""))
        if parsed.get("parse_error"):
            unparseable += 1
        submission[t.id] = {"violated": parsed["violated"], "trace": parsed["trace"]}
    res = score(submission, tasks)
    res["n_unparseable"] = unparseable
    return res
