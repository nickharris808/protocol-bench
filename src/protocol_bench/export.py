"""Export the task set as JSON Lines, for a dataset hub or any other consumer.

One row per task, self-contained: the prompt, the ground-truth label, the binary target, the
citation, and a text rendering of the state machine. The row carries everything needed to run and
score the task without importing this package — but scoring a *trace* still requires the package,
because a trace has to be replayed against the real model to mean anything.
"""

from __future__ import annotations

import json
from typing import Optional

from minicheck import check_safety
from minicheck._core import _reachable

from .llm import build_prompt, render_model
from .tasks import Task, load_tasks


def _machine_facts(task: Task) -> dict:
    """Structural facts about the model, derived rather than asserted."""
    m = task.build()
    parent, order = _reachable(m)
    return {
        "state_fields": list(m.fields),
        "initial_state": dict(zip(m.fields, m.initial)),
        "n_state_fields": len(m.fields),
        "n_reachable_states": len(parent),
        "n_transitions": sum(len(m.transitions(s)) for s in parent),
        "transitions": [
            {
                "from": dict(zip(m.fields, s)),
                "label": label,
                "to": dict(zip(m.fields, ns)),
            }
            for s in order
            for label, ns in m.transitions(s)
        ],
    }


def _counterexample(task: Task) -> Optional[list]:
    """The shortest violating trace, where one exists — re-derived, not stored."""
    res = check_safety(task.build())["properties"][task.property]
    if res["counterexample"] is None:
        return None
    return [{"label": s["label"], "state": s["state"]} for s in res["counterexample"]]


def _fixed_twin_holds(task: Task) -> Optional[bool]:
    """Whether the repaired variant removes the violation, where a twin exists."""
    fixed = task.build_fixed()
    if fixed is None:
        return None
    return bool(check_safety(fixed)["properties"][task.property]["holds"])


def task_to_row(task: Task, mode: str = "model") -> dict:
    facts = _machine_facts(task)
    cex = _counterexample(task)
    return {
        "id": task.id,
        "standards_body": task.standards_body,
        "spec_clause": task.spec_clause,
        "property": task.property,
        "prompt_mode": mode,
        "prompt": build_prompt(task, mode),
        "state_machine": render_model(task),
        "label": task.label,
        "violated": task.is_violated,
        "citation": task.citation,
        "known_finding": task.known_finding,
        "has_fixed_twin": bool(task.fixed_builder),
        "fixed_twin_holds": _fixed_twin_holds(task),
        "n_state_fields": facts["n_state_fields"],
        "n_reachable_states": facts["n_reachable_states"],
        "n_transitions": facts["n_transitions"],
        "state_fields": facts["state_fields"],
        "initial_state": facts["initial_state"],
        "transitions": facts["transitions"],
        "counterexample": cex,
        "counterexample_length": len(cex) if cex else 0,
    }


def export_rows(mode: str = "model", tasks: Optional[list[Task]] = None) -> list[dict]:
    return [task_to_row(t, mode) for t in (tasks or load_tasks())]


def export_jsonl(path: str, mode: str = "model", tasks: Optional[list[Task]] = None) -> int:
    rows = export_rows(mode, tasks)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    return len(rows)
