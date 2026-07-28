"""Adversarial suite: no submission may score well without demonstrating what it claims.

The benchmark's whole proposition is that it can tell a model that FOUND a protocol bug from one
that GUESSED. That distinction lives entirely in whether a claimed counterexample replays against
the model, so these tests attack it directly: fabricated traces, plausible-but-wrong traces, traces
borrowed from the wrong task, and replies engineered to break the parser.

The oracle is: a submission that cannot produce a replaying witness must not out-score the trivial
always-safe guesser on the positive class.
"""

from __future__ import annotations

import json
import time

import pytest

from protocol_bench import load_tasks, score
from protocol_bench.baseline import bfs_baseline
from protocol_bench.llm import parse_response, score_completions
from protocol_bench.score import validate_trace

TASKS = load_tasks()
VIOLATED = [t for t in TASKS if t.is_violated]
SAFE = [t for t in TASKS if not t.is_violated]


# ------------------------------------------------------------------ the attack that scored 1.0
def test_fabricated_traces_score_no_better_than_guessing():
    """The exact submission that used to earn balanced_accuracy 1.0."""
    sub = {t.id: {"violated": t.is_violated, "trace": [{"state": {"TOTALLY": "FAKE"}}]} for t in TASKS}
    res = score(sub)
    assert res["true_positives"] == 0
    assert res["valid_counterexamples"] == 0
    assert res["unreplayed_claims"] == len(VIOLATED)
    assert res["balanced_accuracy"] == 0.5  # exactly the trivial guesser
    # The gap between asserted and demonstrated must be visible, not hidden.
    assert res["accuracy_ignoring_replay"] > res["accuracy"]


def test_an_oracle_that_knows_every_answer_but_proves_nothing_gets_no_credit():
    """Perfect labels, zero traces. Knowing the answer key is not finding the bug."""
    res = score({t.id: {"violated": t.is_violated} for t in TASKS})
    assert res["true_positives"] == 0
    assert res["recall_violated"] == 0.0
    assert res["unreplayed_claims"] == len(VIOLATED)


def test_the_honest_solver_is_unaffected():
    """The fix must not punish a submission that actually does the work."""
    res = score(bfs_baseline())
    assert res["balanced_accuracy"] == 1.0
    assert res["true_positives"] == len(VIOLATED)
    assert res["valid_counterexamples"] == len(VIOLATED)
    assert res["unreplayed_claims"] == 0


def test_claiming_everything_is_violated_is_punished():
    """Spraying detections must not be a winning strategy."""
    res = score({t.id: {"violated": True} for t in TASKS})
    assert res["false_positives"] == len(SAFE)
    assert res["balanced_accuracy"] < 0.5
    assert res["true_positives"] == 0


def test_a_trace_from_the_wrong_task_does_not_replay():
    """Borrowing a valid trace from another model must not transfer credit."""
    good = bfs_baseline()
    donor = VIOLATED[0]
    recipient = VIOLATED[1] if len(VIOLATED) > 1 else None
    if recipient is None:
        pytest.skip("needs two violated tasks")
    res = score({recipient.id: {"violated": True, "trace": good[donor.id]["trace"]}})
    row = next(r for r in res["per_task"] if r["id"] == recipient.id)
    assert row["credited_detection"] is False
    assert res["true_positives"] == 0


def test_a_truncated_valid_trace_does_not_replay():
    """A real prefix that stops before the violation is not a counterexample."""
    good = bfs_baseline()
    t = VIOLATED[0]
    full = good[t.id]["trace"]
    assert len(full) > 1
    res = score({t.id: {"violated": True, "trace": full[:-1]}})
    assert res["true_positives"] == 0
    row = next(r for r in res["per_task"] if r["id"] == t.id)
    assert "does not violate" in row["trace"]["reason"]


def test_a_trace_with_an_illegal_step_does_not_replay():
    """Start and end correct, middle invented — the step check must catch it."""
    good = bfs_baseline()
    t = VIOLATED[0]
    full = [dict(s) for s in good[t.id]["trace"]]
    if len(full) < 3:
        pytest.skip("needs a trace long enough to corrupt the middle")
    full[1] = {"state": dict(full[-1]["state"])}  # teleport to the final state
    res = score({t.id: {"violated": True, "trace": full}})
    assert res["true_positives"] == 0


@pytest.mark.parametrize(
    "trace",
    [
        [],
        None,
        [{}],
        [{"state": {}}],
        [{"state": None}],
        [{"nostate": 1}],
        "not a list",
        [{"state": {"unknown_field": 1}}],
        [{"state": []}],
        list(range(5)),
    ],
)
def test_malformed_traces_are_rejected_not_crashed_on(trace):
    """Every shape of garbage must return valid=False with a reason, never raise, never credit."""
    t = VIOLATED[0]
    res = validate_trace(t, trace)
    assert res["valid"] is False
    assert isinstance(res.get("reason"), str) and res["reason"]


def test_enormous_trace_is_handled():
    """A 100k-step fabricated trace must be rejected promptly, not hang the scorer."""
    t = VIOLATED[0]
    huge = [{"state": dict.fromkeys(t.build().fields, 0)} for _ in range(100_000)]
    start = time.time()
    res = validate_trace(t, huge)
    assert res["valid"] is False
    assert time.time() - start < 10.0


# -------------------------------------------------------------------------------- parser attacks
@pytest.mark.parametrize(
    "reply",
    [
        "",
        "   ",
        "no json at all",
        "{",
        "}",
        "{" * 5000,
        '{"violated": true',
        '{"violated": ',
        "```json\n```",
        "```json\n{broken\n```",
        '{"violated": "yes"}',
        '{"violated": null}',
        '{"violated": [1,2,3]}',
        '{"trace": []}',
        "null",
        "[]",
        '"violated"',
    ],
)
def test_parser_never_crashes_and_never_invents_a_detection(reply):
    """A reply the parser cannot read must fail SAFE: no violation, flagged as a parse error."""
    out = parse_response(reply)
    assert isinstance(out, dict)
    assert out["violated"] in (True, False)
    assert out["trace"] is None or isinstance(out["trace"], list)
    # Nothing in this list is a well-formed detection, so none may produce one silently.
    if out["violated"]:
        assert out["parse_error"] is False


@pytest.mark.parametrize("size", [1_000, 50_000, 250_000])
def test_parser_is_linear_on_adversarial_input(size):
    """P1 regression: the shipped parser was cubic (3.2 KB took 4.4 seconds)."""
    for payload in ("{" * size, "{" * size + '{"violated":true}', '{"k":"' + "{" * size + '","violated":true}'):
        start = time.time()
        parse_response(payload)
        elapsed = time.time() - start
        assert elapsed < 1.0, f"{size} chars took {elapsed:.2f}s"


def test_braces_inside_strings_do_not_confuse_the_scanner():
    out = parse_response('{"note": "a { and a } inside", "violated": true}')
    assert out["violated"] is True
    assert out["parse_error"] is False


def test_parse_errors_are_counted_not_swallowed():
    """A run where the parser ate every reply must be distinguishable from a cautious model."""
    res = score_completions({t.id: "total gibberish" for t in TASKS})
    assert res["n_unparseable"] == len(TASKS)
    assert res["true_positives"] == 0


def test_a_correct_reply_still_parses_end_to_end():
    """Guard against a parser so strict it rejects real submissions."""
    good = bfs_baseline()
    completions = {tid: json.dumps(pred) for tid, pred in good.items()}
    res = score_completions(completions)
    assert res["n_unparseable"] == 0
    assert res["balanced_accuracy"] == 1.0
    assert res["valid_counterexamples"] == len(VIOLATED)


# ---------------------------------------------------------------------------- scoring invariants
def test_confusion_matrix_always_sums_to_the_task_count():
    """Every task lands in exactly one bucket, under every submission shape."""
    for sub in (
        {},
        {t.id: {"violated": True} for t in TASKS},
        {t.id: {"violated": False} for t in TASKS},
        bfs_baseline(),
        {t.id: {"violated": True, "trace": [{"state": {"x": 1}}]} for t in TASKS},
    ):
        res = score(sub)
        total = res["true_positives"] + res["false_positives"] + res["false_negatives"] + res["true_negatives"]
        assert total == res["n_tasks"] == len(TASKS)


def test_credited_detections_never_exceed_claims():
    for sub in ({}, bfs_baseline(), {t.id: {"violated": True} for t in TASKS}):
        res = score(sub)
        assert res["valid_counterexamples"] <= res["detections_claimed"]
        assert res["true_positives"] <= res["valid_counterexamples"]


def test_unknown_task_ids_are_ignored_not_credited():
    res = score({"no_such_task_at_all": {"violated": True, "trace": [{"state": {}}]}})
    assert res["true_positives"] == 0
    assert res["n_tasks"] == len(TASKS)


def test_scoring_is_deterministic():
    sub = bfs_baseline()
    runs = [score(sub) for _ in range(3)]
    assert all(r["balanced_accuracy"] == runs[0]["balanced_accuracy"] for r in runs)
    assert all(r["true_positives"] == runs[0]["true_positives"] for r in runs)


def test_every_task_labelled_violated_really_is():
    """Ground truth must itself be checked — a mislabelled task poisons every score.

    Runs the checker on each task's own model and compares against the published label.
    """
    from minicheck import check_safety

    for t in TASKS:
        model = t.build()
        res = check_safety(model)
        assert res["exhaustive"] is True, f"{t.id} is not exhaustively checkable"
        holds = res["properties"][t.property]["holds"]
        assert holds is (not t.is_violated), (
            f"{t.id}: label says violated={t.is_violated} but checker says holds={holds}"
        )
