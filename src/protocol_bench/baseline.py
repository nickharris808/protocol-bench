"""The reference baselines.

`bfs_baseline` is the one to beat: exhaustive breadth-first reachability, which is sound and
complete over the finite model, so it gets every task right and supplies a replayable trace for
each detection. It is included as the ceiling, not as a competitor — the interesting submissions
are the ones that reason from the SPEC TEXT rather than from an already-formalised model.

`always_safe_baseline` is the floor, and it exists to keep everyone honest: on a task set where
most published procedures are safe, guessing "safe" every time scores well on plain accuracy and
0.5 on balanced accuracy.
"""

from __future__ import annotations

from typing import Optional

from minicheck import check_safety

from .tasks import Task, load_tasks


def bfs_baseline(tasks: Optional[list[Task]] = None) -> dict:
    """Exhaustive reachability. Sound and complete over the finite model."""
    out = {}
    for t in tasks or load_tasks():
        res = check_safety(t.build())["properties"][t.property]
        out[t.id] = {"violated": not res["holds"], "trace": res["counterexample"]}
    return out


def always_safe_baseline(tasks: Optional[list[Task]] = None) -> dict:
    """Predict "safe" for everything. The trivial floor."""
    return {t.id: {"violated": False} for t in tasks or load_tasks()}


def always_violated_baseline(tasks: Optional[list[Task]] = None) -> dict:
    """Predict "violated" for everything, with no trace. Maximum recall, no credibility."""
    return {t.id: {"violated": True} for t in tasks or load_tasks()}


BASELINES = {
    "bfs": bfs_baseline,
    "always-safe": always_safe_baseline,
    "always-violated": always_violated_baseline,
}
