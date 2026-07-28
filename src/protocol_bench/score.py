"""Scoring, including machine-validation of any counterexample a submission claims.

A submission is a mapping from task id to a prediction:

    {"ieee_4way_handshake_krack": {"violated": true, "trace": [{"state": {...}}, ...]}}

`violated` is required. `trace` is optional but is what separates a guess from a finding: if you
supply one it is REPLAYED against the model, and a trace that does not replay is not counted as a
detection.
"""

from __future__ import annotations

from typing import Any, Optional

from .tasks import Task, load_tasks


def validate_trace(task: Task, trace: Optional[list]) -> dict:
    """Replay a claimed counterexample against the model.

    Checks, in order: the trace is non-empty; its first state is the model's initial state; every
    consecutive pair is a real transition; and the final state actually violates the property.

    Returns a dict with ``valid`` and, when false, ``reason``.
    """
    if trace is None:
        return {"supplied": False, "valid": False, "reason": "no trace supplied"}
    if not isinstance(trace, list) or not trace:
        return {"supplied": True, "valid": False, "reason": "trace is empty"}

    model = task.build()
    fields = model.fields

    def as_tuple(step: Any) -> Optional[tuple]:
        st = step.get("state") if isinstance(step, dict) else step
        if isinstance(st, dict):
            try:
                return tuple(st[f] for f in fields)
            except KeyError:
                return None
        if isinstance(st, (list, tuple)) and len(st) == len(fields):
            return tuple(st)
        return None

    states = [as_tuple(s) for s in trace]
    if any(s is None for s in states):
        return {"supplied": True, "valid": False, "reason": f"a step does not name the model's fields {fields}"}

    if states[0] != tuple(model.initial):
        return {
            "supplied": True,
            "valid": False,
            "reason": f"trace does not start at the initial state {model.initial}",
        }

    for i in range(len(states) - 1):
        succ = {ns for _, ns in model.transitions(states[i])}
        if states[i + 1] not in succ:
            return {"supplied": True, "valid": False, "reason": f"step {i} -> {i + 1} is not a transition of the model"}

    pred = model.invariants.get(task.property)
    if pred is None:
        return {"supplied": True, "valid": False, "reason": f"model has no property named {task.property!r}"}
    if pred(model.d(states[-1])):
        return {"supplied": True, "valid": False, "reason": "final state does not violate the property"}

    return {"supplied": True, "valid": True, "length": len(states)}


def score(submission: dict, tasks: Optional[list[Task]] = None) -> dict:
    """Score a submission.

    The headline metric is **balanced accuracy** — the mean of per-class recall — because the task
    set is deliberately imbalanced (most published procedures are safe). Plain accuracy is also
    reported, alongside the accuracy of a trivial always-safe guesser, so the two cannot be
    confused.
    """
    tasks = tasks or load_tasks()
    per_task, tp = [], 0
    fp = fn = tn = 0
    valid_traces = 0

    for t in tasks:
        entry = submission.get(t.id) or {}
        pred = bool(entry.get("violated", False))
        tr = (
            validate_trace(t, entry.get("trace"))
            if pred
            else {"supplied": False, "valid": False, "reason": "no violation predicted"}
        )
        if pred and tr["valid"]:
            valid_traces += 1

        if pred and t.is_violated:
            tp += 1
            outcome = "true_positive"
        elif pred and not t.is_violated:
            fp += 1
            outcome = "false_positive"
        elif not pred and t.is_violated:
            fn += 1
            outcome = "false_negative"
        else:
            tn += 1
            outcome = "true_negative"

        per_task.append({"id": t.id, "label": t.label, "predicted_violated": pred, "outcome": outcome, "trace": tr})

    n = len(tasks)
    n_pos = sum(1 for t in tasks if t.is_violated)
    n_neg = n - n_pos
    recall_pos = tp / n_pos if n_pos else 0.0
    recall_neg = tn / n_neg if n_neg else 0.0

    return {
        "n_tasks": n,
        "accuracy": (tp + tn) / n if n else 0.0,
        "balanced_accuracy": (recall_pos + recall_neg) / 2,
        "recall_violated": recall_pos,
        "recall_safe": recall_neg,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "valid_counterexamples": valid_traces,
        "detections_claimed": tp + fp,
        "trivial_always_safe_accuracy": n_neg / n if n else 0.0,
        "per_task": per_task,
    }
