"""Command line: run a baseline, or score a submission file."""

from __future__ import annotations

import argparse
import json
import sys

from .baseline import BASELINES
from .llm import MODES, build_prompts, score_completions
from .score import score
from .tasks import dataset_info, load_tasks


def _summary(res: dict) -> str:
    return (
        f"  tasks                      {res['n_tasks']}\n"
        f"  balanced accuracy          {res['balanced_accuracy']:.3f}   <- headline\n"
        f"  accuracy                   {res['accuracy']:.3f}\n"
        f"  (trivial always-safe acc.  {res['trivial_always_safe_accuracy']:.3f})\n"
        f"  recall on violated         {res['recall_violated']:.3f}\n"
        f"  recall on safe             {res['recall_safe']:.3f}\n"
        f"  detections claimed         {res['detections_claimed']}\n"
        f"  valid counterexamples      {res['valid_counterexamples']}\n"
        f"  TP {res['true_positives']}  FP {res['false_positives']}  "
        f"FN {res['false_negatives']}  TN {res['true_negatives']}"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="protocol-bench", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_info = sub.add_parser("info", help="dataset version and task counts")
    p_info.add_argument("--json", action="store_true")

    sub.add_parser("list", help="list every task and its label")

    p_run = sub.add_parser("run", help="run a built-in baseline and score it")
    p_run.add_argument("baseline", choices=sorted(BASELINES))
    p_run.add_argument("-o", "--out", help="write the raw submission JSON here")
    p_run.add_argument("--json", action="store_true")

    p_score = sub.add_parser("score", help="score a submission JSON file")
    p_score.add_argument("submission")
    p_score.add_argument("--json", action="store_true")

    p_prompts = sub.add_parser("prompts", help="emit one prompt per task for a language model")
    p_prompts.add_argument("--mode", choices=list(MODES), default="model")
    p_prompts.add_argument("-o", "--out", help="write prompts JSON here (default: stdout)")

    p_llm = sub.add_parser("score-completions", help="score raw model replies (task id -> completion text)")
    p_llm.add_argument("completions")
    p_llm.add_argument("--json", action="store_true")

    p_export = sub.add_parser("export", help="export the task set as JSON Lines")
    p_export.add_argument("-o", "--out", required=True)
    p_export.add_argument("--mode", choices=list(MODES), default="model", help="which prompt to embed in each row")

    a = ap.parse_args(argv)

    if a.cmd == "info":
        info = dataset_info()
        print(json.dumps(info, indent=2) if a.json else f"{info['name']} v{info['version']}: {info['n_tasks']} tasks")
        return 0

    if a.cmd == "list":
        for t in load_tasks():
            print(f"{t.label:24s} {t.standards_body:6s} {t.id:38s} {t.property}")
        return 0

    if a.cmd == "run":
        submission = BASELINES[a.baseline]()
        if a.out:
            with open(a.out, "w") as fh:
                json.dump(submission, fh, indent=2, default=str)
        res = score(submission)
        print(json.dumps(res, indent=2, default=str) if a.json else f"baseline: {a.baseline}\n{_summary(res)}")
        return 0

    if a.cmd == "prompts":
        ps = build_prompts(a.mode)
        text = json.dumps(ps, indent=2)
        if a.out:
            with open(a.out, "w") as fh:
                fh.write(text)
            print(f"wrote {len(ps)} prompts ({a.mode} mode) to {a.out}")
        else:
            print(text)
        return 0

    if a.cmd == "score-completions":
        with open(a.completions) as fh:
            completions = json.load(fh)
        res = score_completions(completions)
        print(
            json.dumps(res, indent=2, default=str)
            if a.json
            else _summary(res) + f"\n  unparseable replies       {res['n_unparseable']}"
        )
        return 0

    if a.cmd == "export":
        from .export import export_jsonl

        n = export_jsonl(a.out, mode=a.mode)
        print(f"wrote {n} rows to {a.out}")
        return 0

    if a.cmd == "score":
        with open(a.submission) as fh:
            submission = json.load(fh)
        res = score(submission)
        print(json.dumps(res, indent=2, default=str) if a.json else _summary(res))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
