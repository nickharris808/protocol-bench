"""protocol-bench — ground-truth safety verdicts for published IEEE 802.11 and 3GPP procedures.

Fifteen real, published procedures, each with a named safety property and a ground-truth label.
Where the property fails, a shortest counterexample and (for two of them) a proven-fixed twin.

>>> from protocol_bench import load_tasks, score
>>> tasks = load_tasks()
>>> len(tasks)
15
>>> score({t.id: {"violated": False} for t in tasks})["balanced_accuracy"]
0.5
"""

from .baseline import BASELINES, always_safe_baseline, bfs_baseline
from .llm import (
    MODES,
    build_prompt,
    build_prompts,
    parse_response,
    render_model,
    score_completions,
)
from .score import score, validate_trace
from .tasks import CANDIDATE, KNOWN, LABELS, SAFE, Task, dataset_info, load_tasks

__all__ = [
    "Task",
    "load_tasks",
    "dataset_info",
    "score",
    "validate_trace",
    "bfs_baseline",
    "always_safe_baseline",
    "BASELINES",
    "build_prompt",
    "build_prompts",
    "render_model",
    "parse_response",
    "score_completions",
    "MODES",
    "KNOWN",
    "CANDIDATE",
    "SAFE",
    "LABELS",
    "__version__",
]
__version__ = "1.0.0"
