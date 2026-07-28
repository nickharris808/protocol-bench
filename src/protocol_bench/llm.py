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


def parse_response(text: str) -> dict:
    """Extract a prediction from a model's reply, tolerantly.

    Handles a bare JSON object, a fenced code block, or JSON with prose around it. A reply that
    cannot be parsed is scored as `violated: false` — an unreadable answer is not a detection.
    """
    if isinstance(text, dict):
        raw = text
    else:
        candidates = _FENCE.findall(text or "")
        candidates.append(text or "")
        raw = None
        for c in candidates:
            c = c.strip()
            start = c.find("{")
            while start != -1 and raw is None:
                for end in range(len(c), start, -1):
                    try:
                        obj = json.loads(c[start:end])
                    except Exception:
                        continue
                    if isinstance(obj, dict) and "violated" in obj:
                        raw = obj
                    break
                start = c.find("{", start + 1)
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
