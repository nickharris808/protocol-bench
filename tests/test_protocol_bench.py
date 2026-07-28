"""Tests for protocol-bench.

Two things must hold or the benchmark is worthless: the ground truth must match what an exhaustive
checker actually finds on the shipped models, and a claimed counterexample must be REPLAYED rather
than trusted.
"""

import json

import pytest
from protocol_bench import (
    BASELINES,
    CANDIDATE,
    KNOWN,
    SAFE,
    always_safe_baseline,
    bfs_baseline,
    dataset_info,
    load_tasks,
    score,
    validate_trace,
)
from protocol_bench.cli import main as cli_main

from minicheck import check_safety

TASKS = load_tasks()


# --------------------------------------------------------------------------- dataset integrity
def test_dataset_has_the_expected_shape():
    info = dataset_info()
    assert info["n_tasks"] == len(TASKS) == 15
    assert set(info["label_values"]) == {KNOWN, CANDIDATE, SAFE}


def test_every_task_has_a_valid_label_and_a_property():
    for t in TASKS:
        assert t.label in (KNOWN, CANDIDATE, SAFE)
        assert t.property
        assert t.spec_clause
        assert t.standards_body in ("IEEE", "3GPP")


def test_task_ids_are_unique():
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids))


def test_a_known_counterexample_carries_a_citation_and_a_candidate_does_not():
    """This is the honesty rule of the label taxonomy: KNOWN means published, CANDIDATE means
    found-but-uncited and therefore explicitly unconfirmed."""
    for t in TASKS:
        if t.label == KNOWN:
            assert t.citation, f"{t.id} is KNOWN but has no citation"
        if t.label == CANDIDATE:
            assert not t.citation, f"{t.id} is CANDIDATE yet carries a citation"


def test_krack_is_present_and_cited():
    krack = next(t for t in TASKS if t.id == "ieee_4way_handshake_krack")
    assert krack.label == KNOWN
    assert "Vanhoef" in krack.citation
    assert krack.property == "nonce_never_reused"


# --------------------------------------------------------------------------- ground truth is real
@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_ground_truth_matches_exhaustive_reachability(task):
    """The shipped label must be what an exhaustive checker actually finds on the shipped model."""
    res = check_safety(task.build())["properties"][task.property]
    assert res["holds"] is not task.is_violated


@pytest.mark.parametrize("task", [t for t in TASKS if t.fixed_builder], ids=[t.id for t in TASKS if t.fixed_builder])
def test_the_fixed_twin_actually_repairs_the_violation(task):
    """A counterexample nobody can remove is a modelling artefact. Each fixed twin must hold."""
    assert task.is_violated
    res = check_safety(task.build_fixed())["properties"][task.property]
    assert res["holds"] is True


# --------------------------------------------------------------------------- trace validation
def test_a_real_bfs_trace_validates():
    task = next(t for t in TASKS if t.id == "ieee_4way_handshake_krack")
    trace = check_safety(task.build())["properties"][task.property]["counterexample"]
    v = validate_trace(task, trace)
    assert v["valid"] is True and v["length"] == len(trace)


def test_a_missing_trace_does_not_validate():
    task = TASKS[0]
    assert validate_trace(task, None)["valid"] is False
    assert validate_trace(task, [])["valid"] is False


def test_a_trace_that_does_not_start_at_the_initial_state_is_rejected():
    task = next(t for t in TASKS if t.id == "ieee_4way_handshake_krack")
    trace = check_safety(task.build())["properties"][task.property]["counterexample"]
    v = validate_trace(task, trace[1:])  # drop the initial state
    assert v["valid"] is False
    assert "initial state" in v["reason"]


def test_a_trace_with_a_fabricated_step_is_rejected():
    """Splicing out a middle state breaks the transition relation and must be caught."""
    task = next(t for t in TASKS if t.id == "ieee_4way_handshake_krack")
    trace = check_safety(task.build())["properties"][task.property]["counterexample"]
    if len(trace) < 3:
        pytest.skip("trace too short to splice")
    spliced = [trace[0]] + trace[2:]
    v = validate_trace(task, spliced)
    assert v["valid"] is False
    assert "not a transition" in v["reason"]


def test_a_trace_ending_in_a_non_violating_state_is_rejected():
    task = next(t for t in TASKS if t.id == "ieee_4way_handshake_krack")
    trace = check_safety(task.build())["properties"][task.property]["counterexample"]
    v = validate_trace(task, trace[:1])  # initial state only; it does not violate
    assert v["valid"] is False
    assert "does not violate" in v["reason"]


def test_a_trace_with_unknown_fields_is_rejected():
    task = TASKS[0]
    v = validate_trace(task, [{"state": {"nonsense": 1}}])
    assert v["valid"] is False


# --------------------------------------------------------------------------- scoring
def test_bfs_baseline_is_perfect_and_every_detection_replays():
    res = score(bfs_baseline())
    assert res["balanced_accuracy"] == 1.0
    assert res["false_positives"] == 0 and res["false_negatives"] == 0
    # every claimed detection is backed by a trace that actually replays
    assert res["valid_counterexamples"] == res["detections_claimed"] == 2


def test_always_safe_scores_high_accuracy_but_chance_balanced_accuracy():
    """The reason balanced accuracy is the headline: plain accuracy flatters a trivial guesser."""
    res = score(always_safe_baseline())
    assert res["accuracy"] == pytest.approx(13 / 15)
    assert res["balanced_accuracy"] == 0.5
    assert res["accuracy"] == res["trivial_always_safe_accuracy"]


def test_always_violated_claims_everything_and_validates_nothing():
    res = score(BASELINES["always-violated"]())
    assert res["detections_claimed"] == 15
    assert res["valid_counterexamples"] == 0  # no traces supplied -> no credit
    assert res["false_positives"] == 13


def test_an_empty_submission_is_scored_as_all_safe():
    res = score({})
    assert res["balanced_accuracy"] == 0.5
    assert res["false_negatives"] == 2


def test_a_detection_with_a_bogus_trace_still_counts_as_a_prediction_but_not_as_validated():
    """Separating 'predicted correctly' from 'proved it' is the point of the trace column."""
    task = next(t for t in TASKS if t.id == "ieee_4way_handshake_krack")
    res = score({task.id: {"violated": True, "trace": [{"state": {"bogus": 1}}]}})
    assert res["true_positives"] == 1
    assert res["valid_counterexamples"] == 0


def test_per_task_rows_are_complete():
    res = score(bfs_baseline())
    assert len(res["per_task"]) == 15
    assert {r["outcome"] for r in res["per_task"]} <= {
        "true_positive",
        "true_negative",
        "false_positive",
        "false_negative",
    }


# --------------------------------------------------------------------------- CLI
def test_cli_info_and_list(capsys):
    assert cli_main(["info"]) == 0
    assert "15 tasks" in capsys.readouterr().out
    assert cli_main(["list"]) == 0
    assert "ieee_4way_handshake_krack" in capsys.readouterr().out


def test_cli_run_reports_the_headline_metric(capsys):
    assert cli_main(["run", "bfs"]) == 0
    out = capsys.readouterr().out
    assert "balanced accuracy" in out and "1.000" in out


def test_cli_round_trips_a_submission_file(tmp_path, capsys):
    p = tmp_path / "sub.json"
    assert cli_main(["run", "bfs", "-o", str(p)]) == 0
    capsys.readouterr()
    assert json.loads(p.read_text())
    assert cli_main(["score", str(p)]) == 0
    assert "balanced accuracy" in capsys.readouterr().out


def test_cli_json_output_is_parseable(capsys):
    assert cli_main(["run", "always-safe", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["balanced_accuracy"] == 0.5
