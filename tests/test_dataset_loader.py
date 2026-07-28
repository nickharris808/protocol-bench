"""Tests for the dataset loader shipped alongside the JSONL."""

import json
import pathlib
import sys

import pytest

DATASET_DIR = pathlib.Path(__file__).resolve().parents[1] / "dataset"
sys.path.insert(0, str(DATASET_DIR))

import load_dataset as ld  # noqa: E402


def test_the_jsonl_exists_and_parses():
    rows = ld.load()
    assert len(rows) == 15
    assert all(isinstance(r, dict) for r in rows)


def test_the_shipped_file_matches_what_the_package_would_generate():
    """Guards against the committed data drifting away from the code."""
    from protocol_bench.export import export_rows

    shipped = {r["id"]: r for r in ld.load()}
    live = {r["id"]: r for r in export_rows()}
    assert set(shipped) == set(live)
    for k in shipped:
        assert shipped[k] == live[k], k


def test_stats_are_derived_from_the_rows():
    s = ld.stats()
    assert s["n_rows"] == 15
    assert s["n_violated"] == 2 and s["n_safe"] == 13
    assert s["by_standards_body"] == {"IEEE": 8, "3GPP": 7}
    assert s["n_with_counterexample"] == 2
    assert s["trivial_always_safe_accuracy"] == pytest.approx(13 / 15, abs=1e-4)


def test_a_missing_file_gives_an_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError) as e:
        ld.load(tmp_path / "nope.jsonl")
    assert "--regenerate" in str(e.value)


def test_regenerate_round_trips(tmp_path):
    p = tmp_path / "out.jsonl"
    assert ld.regenerate(p) == 15
    assert len(ld.load(p)) == 15


def test_cli_stats_and_default(capsys):
    assert ld.main(["--stats"]) == 0
    assert json.loads(capsys.readouterr().out)["n_rows"] == 15
    assert ld.main([]) == 0
    assert "15 rows" in capsys.readouterr().out


def test_cli_regenerate(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ld, "DATA", tmp_path / "regen.jsonl")
    assert ld.main(["--regenerate"]) == 0
    assert "wrote 15 rows" in capsys.readouterr().out
