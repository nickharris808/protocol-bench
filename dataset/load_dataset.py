"""Loader for the Protocol-Bench dataset.

Works three ways, in order of preference:

    from load_dataset import load
    rows = load()                       # plain Python, no dependencies

    ds = load_hf()                      # a `datasets.Dataset`, if `datasets` is installed

    python load_dataset.py --stats      # summary from the command line

The JSONL beside this file is the authoritative copy. If `protocol-bench` is installed, `regenerate()`
rebuilds it from the live models so the data can never drift from the code.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
DATA = HERE / "protocol_bench.jsonl"


def load(path: str | pathlib.Path | None = None) -> list[dict]:
    """Every row, as plain dicts. No third-party dependency."""
    p = pathlib.Path(path) if path else DATA
    if not p.exists():
        raise FileNotFoundError(f"{p} not found. Regenerate it with:  python load_dataset.py --regenerate")
    with p.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_hf(path: str | pathlib.Path | None = None):
    """A `datasets.Dataset`. Requires `pip install datasets`."""
    try:
        from datasets import Dataset
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise ImportError("pip install datasets") from e
    return Dataset.from_list(load(path))


def regenerate(path: str | pathlib.Path | None = None, mode: str = "model") -> int:
    """Rebuild the JSONL from the installed package, so data cannot drift from code."""
    from protocol_bench.export import export_jsonl

    return export_jsonl(str(pathlib.Path(path) if path else DATA), mode=mode)


def stats(rows: list[dict] | None = None) -> dict:
    """Summary counts, derived from the rows themselves."""
    rows = rows if rows is not None else load()
    labels: dict[str, int] = {}
    bodies: dict[str, int] = {}
    for r in rows:
        labels[r["label"]] = labels.get(r["label"], 0) + 1
        bodies[r["standards_body"]] = bodies.get(r["standards_body"], 0) + 1
    violated = sum(1 for r in rows if r["violated"])
    return {
        "n_rows": len(rows),
        "by_label": labels,
        "by_standards_body": bodies,
        "n_violated": violated,
        "n_safe": len(rows) - violated,
        "trivial_always_safe_accuracy": round((len(rows) - violated) / len(rows), 4) if rows else 0,
        "n_with_counterexample": sum(1 for r in rows if r["counterexample"]),
        "n_with_fixed_twin": sum(1 for r in rows if r["has_fixed_twin"]),
        "total_transitions": sum(r["n_transitions"] for r in rows),
        "total_reachable_states": sum(r["n_reachable_states"] for r in rows),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", action="store_true", help="print summary counts")
    ap.add_argument("--regenerate", action="store_true", help="rebuild the JSONL from the package")
    ap.add_argument("--mode", choices=("model", "spec"), default="model")
    a = ap.parse_args(argv)

    if a.regenerate:
        n = regenerate(mode=a.mode)
        print(f"wrote {n} rows to {DATA} ({a.mode} mode)")
        return 0

    rows = load()
    if a.stats:
        print(json.dumps(stats(rows), indent=2))
    else:
        print(f"{len(rows)} rows. Use --stats for a summary.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
