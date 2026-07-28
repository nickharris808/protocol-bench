"""Scoring, including machine-validation of any counterexample a submission claims.

A submission is a mapping from task id to a prediction:

    {"ieee_4way_handshake_krack": {"violated": true, "trace": [{"state": {...}}, ...]}}

`violated` is required. `trace` is what separates a guess from a finding: it is REPLAYED against the
model, and **a detection is credited only when its trace replays**. This is the benchmark's whole
point, so it is enforced in the arithmetic rather than merely reported alongside it.

Concretely, for a task that really is violated:

===========================  ================  ==================================================
submission                   scored as         why
===========================  ================  ==================================================
violated + replaying trace   true positive     the claim is backed by a witness
violated + bogus trace       false negative    the bug was not actually found, only guessed at
violated + no trace          false negative    same: an unsupported assertion earns no credit
not violated                 false negative    missed it
===========================  ================  ==================================================

and for a task that is safe, *any* violation claim is a false positive whether or not a trace came
with it — you cannot produce a replaying counterexample for a property that holds, so a trace here is
either invalid or the model is wrong about something else.

This closes a defect in the shipped version, where tp/fp/fn/tn were computed from ``violated`` alone
and the replay result was carried in the report but never consulted. A submission that answered
``violated: true`` with a trace of pure nonsense scored ``balanced_accuracy 1.0`` — the exact failure
the benchmark exists to detect. ``accuracy_ignoring_replay`` is still reported so the gap between
"claimed" and "demonstrated" is visible, but the headline number is the demonstrated one.
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
    per_task = []
    tp = fp = fn = tn = 0
    valid_traces = 0
    unreplayed_claims = 0
    # Secondary counters that ignore replay entirely, kept only to expose the gap between what a
    # submission claimed and what it demonstrated.
    tp_claimed = tn_claimed = 0

    for t in tasks:
        entry = submission.get(t.id)
        # A submission comes from a user or a model, so a malformed entry is expected input rather
        # than a programmer error. Anything that is not an object is treated as NO prediction —
        # which is the conservative reading: it claims nothing, so it is credited with nothing.
        if not isinstance(entry, dict):
            entry = {}
        pred = bool(entry.get("violated", False))
        tr = (
            validate_trace(t, entry.get("trace"))
            if pred
            else {"supplied": False, "valid": False, "reason": "no violation predicted"}
        )
        # A detection counts only when a witness replays against the model.
        credited = pred and bool(tr["valid"])
        if credited:
            valid_traces += 1
        elif pred:
            unreplayed_claims += 1

        if t.is_violated:
            if credited:
                tp += 1
                outcome = "true_positive"
            else:
                fn += 1
                outcome = "false_negative_unreplayed" if pred else "false_negative"
            tp_claimed += 1 if pred else 0
        else:
            if pred:
                fp += 1
                outcome = "false_positive"
            else:
                tn += 1
                outcome = "true_negative"
                tn_claimed += 1

        per_task.append(
            {
                "id": t.id,
                "label": t.label,
                "predicted_violated": pred,
                "credited_detection": credited,
                "outcome": outcome,
                "trace": tr,
            }
        )

    n = len(tasks)
    n_pos = sum(1 for t in tasks if t.is_violated)
    n_neg = n - n_pos
    recall_pos = tp / n_pos if n_pos else 0.0
    recall_neg = tn / n_neg if n_neg else 0.0

    return {
        "n_tasks": n,
        # Headline metrics. Every positive here is backed by a trace that replayed.
        "accuracy": (tp + tn) / n if n else 0.0,
        "balanced_accuracy": (recall_pos + recall_neg) / 2,
        "recall_violated": recall_pos,
        "recall_safe": recall_neg,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "valid_counterexamples": valid_traces,
        "detections_claimed": sum(1 for r in per_task if r["predicted_violated"]),
        "unreplayed_claims": unreplayed_claims,
        # Secondary: what the score WOULD have been if claims were taken at face value. A large gap
        # between this and `accuracy` means the submission is asserting more than it can show.
        "accuracy_ignoring_replay": (tp_claimed + tn_claimed) / n if n else 0.0,
        "trivial_always_safe_accuracy": n_neg / n if n else 0.0,
        "per_task": per_task,
    }
