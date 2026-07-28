"""Tests for the language-model evaluation harness.

No network and no model calls: the harness builds prompts and scores replies, so both halves are
testable with synthesised completions.
"""

import json

import pytest
from protocol_bench import (
    MODES,
    build_prompt,
    build_prompts,
    load_tasks,
    parse_response,
    render_model,
    score_completions,
)

from minicheck import check_safety

TASKS = load_tasks()
KRACK = next(t for t in TASKS if t.id == "ieee_4way_handshake_krack")


# --------------------------------------------------------------------------- prompt construction
@pytest.mark.parametrize("mode", MODES)
def test_every_task_builds_a_prompt_in_every_mode(mode):
    for t in TASKS:
        p = build_prompt(t, mode)
        assert t.property in p
        assert t.spec_clause in p
        assert '"violated"' in p  # the response contract is always present


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        build_prompt(KRACK, "telepathy")


def test_model_mode_renders_the_whole_reachable_transition_table():
    """The prompt must be a faithful rendering: every reachable edge appears."""
    rendered = render_model(KRACK)
    m = KRACK.build()
    from minicheck._core import _reachable

    parent, _ = _reachable(m)
    n_edges = sum(len(m.transitions(s)) for s in parent)
    # count only the indented edge lines; the section header also contains "-->"
    edge_lines = [ln for ln in rendered.splitlines() if ln.startswith("  ") and "-->" in ln]
    assert len(edge_lines) == n_edges
    assert str(dict(zip(m.fields, m.initial))) in rendered


def test_model_mode_does_not_leak_the_answer():
    """The prompt must not tell the model whether the property holds."""
    p = build_prompt(KRACK, "model").lower()
    for giveaway in ("known_counterexample", "proven_safe", "krack", "vanhoef", "cve-"):
        assert giveaway not in p


def test_spec_mode_omits_the_state_machine():
    p = build_prompt(KRACK, "spec")
    assert "-->" not in p  # no transition table
    assert "4-way handshake" in p.lower()  # but the procedure IS described


def test_build_prompts_covers_every_task():
    ps = build_prompts("model")
    assert set(ps) == {t.id for t in TASKS}


# --------------------------------------------------------------------------- response parsing
def test_parses_a_bare_json_object():
    r = parse_response('{"violated": true, "trace": [{"state": {"a": 1}}]}')
    assert r["violated"] is True and len(r["trace"]) == 1 and r["parse_error"] is False


def test_parses_a_fenced_code_block():
    r = parse_response('Here you go:\n```json\n{"violated": false}\n```\nHope that helps.')
    assert r["violated"] is False and r["parse_error"] is False


def test_parses_json_surrounded_by_prose():
    r = parse_response('After analysis I conclude {"violated": true} — the nonce repeats.')
    assert r["violated"] is True


def test_unparseable_prose_is_scored_as_no_detection():
    r = parse_response("I think this protocol is probably fine, honestly.")
    assert r["violated"] is False and r["parse_error"] is True


def test_a_dict_passes_through():
    r = parse_response({"violated": True, "trace": []})
    assert r["violated"] is True and r["parse_error"] is False


def test_a_non_list_trace_is_discarded():
    r = parse_response('{"violated": true, "trace": "I could not construct one"}')
    assert r["violated"] is True and r["trace"] is None


# --------------------------------------------------------------------------- scoring completions
def _perfect_completions():
    """What a model that solved every task exactly would emit."""
    out = {}
    for t in TASKS:
        res = check_safety(t.build())["properties"][t.property]
        payload = {"violated": not res["holds"]}
        if res["counterexample"]:
            payload["trace"] = [{"state": s["state"]} for s in res["counterexample"]]
        out[t.id] = "```json\n" + json.dumps(payload, default=str) + "\n```"
    return out


def test_a_perfect_model_scores_one_and_every_trace_replays():
    res = score_completions(_perfect_completions())
    assert res["balanced_accuracy"] == 1.0
    assert res["valid_counterexamples"] == res["detections_claimed"] == 2
    assert res["n_unparseable"] == 0


def test_a_model_that_answers_in_prose_is_marked_unparseable_not_safe():
    res = score_completions({t.id: "It seems fine to me." for t in TASKS})
    assert res["n_unparseable"] == 15
    assert res["balanced_accuracy"] == 0.5  # scored as all-safe


def test_a_model_that_claims_everything_without_traces_validates_nothing():
    res = score_completions({t.id: '{"violated": true}' for t in TASKS})
    assert res["detections_claimed"] == 15
    assert res["valid_counterexamples"] == 0
    assert res["false_positives"] == 13


def test_a_correct_verdict_with_a_fabricated_trace_gets_the_verdict_but_not_the_proof():
    """This is the property the whole harness exists to measure."""
    completions = {t.id: '{"violated": false}' for t in TASKS}
    completions[KRACK.id] = json.dumps(
        {
            "violated": True,
            "trace": [{"state": {"ptk_installed": True, "tx_nonce": 9, "nonce_reused": True}}],
        }
    )
    res = score_completions(completions)
    assert res["true_positives"] == 1  # right answer
    assert res["valid_counterexamples"] == 0  # unproven: does not start at the initial state
    row = next(r for r in res["per_task"] if r["id"] == KRACK.id)
    assert row["trace"]["valid"] is False
    assert "initial state" in row["trace"]["reason"]


def test_missing_completions_are_scored_as_safe():
    res = score_completions({})
    assert res["n_unparseable"] == 15
    assert res["false_negatives"] == 2


# --------------------------------------------------------------------------- export / dataset rows
def test_export_rows_are_self_contained_and_complete():
    from protocol_bench.export import export_rows

    rows = export_rows("model")
    assert len(rows) == len(TASKS)
    required = {
        "id",
        "standards_body",
        "spec_clause",
        "property",
        "prompt",
        "state_machine",
        "label",
        "violated",
        "citation",
        "has_fixed_twin",
        "prompt_mode",
    }
    for r in rows:
        assert required <= set(r)
        assert isinstance(r["violated"], bool)
        assert r["prompt"]


def test_export_jsonl_round_trips(tmp_path):
    import json as _json

    from protocol_bench.export import export_jsonl

    p = tmp_path / "pb.jsonl"
    n = export_jsonl(str(p), mode="spec")
    lines = p.read_text().strip().splitlines()
    assert n == len(lines) == len(TASKS)
    row = _json.loads(lines[0])
    assert row["prompt_mode"] == "spec"
    assert "-->" not in row["prompt"]  # spec mode hides the transition table
    assert "-->" in row["state_machine"]  # but the rendering is still carried


def test_exported_labels_agree_with_the_binary_target():
    from protocol_bench.export import export_rows

    for r in export_rows():
        assert r["violated"] is (r["label"] != "PROVEN_SAFE")


# --------------------------------------------------------------------------- CLI, LLM flow
def test_cli_prompts_and_score_completions_round_trip(tmp_path, capsys):
    import json as _json

    from protocol_bench.cli import main as cli_main

    pp = tmp_path / "prompts.json"
    assert cli_main(["prompts", "--mode", "model", "-o", str(pp)]) == 0
    capsys.readouterr()
    prompts = _json.loads(pp.read_text())
    assert len(prompts) == len(TASKS)

    # a "model" that answers safe to everything, in prose-wrapped JSON
    cp = tmp_path / "completions.json"
    cp.write_text(_json.dumps(dict.fromkeys(prompts, 'I conclude {"violated": false}')))
    assert cli_main(["score-completions", str(cp)]) == 0
    out = capsys.readouterr().out
    assert "balanced accuracy" in out and "unparseable replies       0" in out


def test_cli_export_writes_jsonl(tmp_path, capsys):
    from protocol_bench.cli import main as cli_main

    p = tmp_path / "out.jsonl"
    assert cli_main(["export", "-o", str(p)]) == 0
    assert "15 rows" in capsys.readouterr().out
    assert len(p.read_text().strip().splitlines()) == 15


# --------------------------------------------------------------------------- enriched export
def test_rows_carry_the_machine_structure_and_the_counterexample():
    from protocol_bench.export import export_rows

    rows = {r["id"]: r for r in export_rows()}
    krack = rows["ieee_4way_handshake_krack"]
    assert krack["n_reachable_states"] == 7
    assert krack["n_transitions"] == 11
    assert krack["counterexample_length"] == 4
    assert krack["counterexample"][0]["label"] is None  # the initial state
    assert krack["counterexample"][-1]["state"]["nonce_reused"] is True
    assert krack["fixed_twin_holds"] is True  # the repair really repairs


def test_every_violated_row_has_a_counterexample_and_safe_rows_do_not():
    from protocol_bench.export import export_rows

    for r in export_rows():
        if r["violated"]:
            assert r["counterexample"], r["id"]
            assert r["counterexample_length"] > 0
        else:
            assert r["counterexample"] is None
            assert r["counterexample_length"] == 0


def test_exported_transitions_match_the_live_model():
    from minicheck._core import _reachable
    from protocol_bench.export import export_rows

    for r in export_rows():
        task = next(t for t in TASKS if t.id == r["id"])
        m = task.build()
        parent, _ = _reachable(m)
        assert r["n_reachable_states"] == len(parent)
        assert r["n_transitions"] == sum(len(m.transitions(s)) for s in parent)
        assert len(r["transitions"]) == r["n_transitions"]
        assert r["state_fields"] == list(m.fields)


def test_exported_counterexamples_replay():
    """The strongest check: every trace shipped in the dataset validates against its own model."""
    from protocol_bench import validate_trace
    from protocol_bench.export import export_rows

    for r in export_rows():
        if not r["counterexample"]:
            continue
        task = next(t for t in TASKS if t.id == r["id"])
        assert validate_trace(task, r["counterexample"])["valid"] is True, r["id"]
