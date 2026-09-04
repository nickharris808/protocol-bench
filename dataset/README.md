---
license: mit
task_categories:
  - text-classification
  - question-answering
language:
  - en
tags:
  - formal-methods
  - protocol-verification
  - security
  - model-checking
  - ieee-802-11
  - 3gpp
  - reasoning
  - counterexamples
pretty_name: Protocol-Bench
size_categories:
  - n<1K
configs:
  - config_name: default
    data_files: protocol_bench.jsonl
---

# Protocol-Bench

**15 published IEEE 802.11 and 3GPP procedures with ground-truth safety verdicts — and, where a
property fails, the shortest counterexample trace that proves it.**

Most reasoning benchmarks accept an answer. This one asks for a **proof**: if a model says a protocol
is broken, it must supply a trace that starts at the initial state, moves only along real
transitions, and ends in a genuinely violating state. Traces are replayed mechanically. A
plausible-sounding trace that does not replay earns nothing.

## Why the metric is shaped this way

The task set is **deliberately imbalanced** — 13 of 15 procedures are safe, which is what the
published-procedure population actually looks like.

| Strategy | Accuracy | Balanced accuracy | Valid counterexamples |
|---|---|---|---|
| Answer "safe" every time | **0.867** | 0.500 | 0 |
| Answer "violated" every time | 0.133 | 0.500 | **0** |
| Exhaustive model checker | 1.000 | **1.000** | **2** |

Plain accuracy is nearly uninformative here — hence **balanced accuracy** as the headline, and the
**valid-counterexample count** as the column separating a detector from a guesser.

There is a second reason, specific to language models: a verdict is separable from the reasoning that
should justify it. *"The WPA2 four-way handshake"* is strongly associated with *"vulnerable"* in any
training corpus, so a model can be right about it having done no reasoning at all. Recalling a CVE
does not produce a replaying trace; reasoning about the state machine does.

## Schema

21 fields per row. Everything is derived from the live models at export time, never hand-maintained.

| Field | Type | Description |
|---|---|---|
| `id` | string | Task identifier |
| `standards_body` | string | `IEEE` (8) or `3GPP` (7) |
| `spec_clause` | string | The published clause modelled |
| `property` | string | Name of the safety property that must hold |
| `label` | string | `KNOWN_COUNTEREXAMPLE` \| `CANDIDATE_COUNTEREXAMPLE` \| `PROVEN_SAFE` |
| `violated` | bool | Binary target, derived from `label` |
| `prompt` | string | Ready-to-use prompt |
| `prompt_mode` | string | `model` or `spec` (see below) |
| `state_machine` | string | Human-readable rendering of the machine |
| `state_fields` | list[string] | State variable names, in order |
| `initial_state` | object | Field → initial value |
| `transitions` | list[object] | Every reachable edge: `{from, label, to}` |
| `n_state_fields` | int | Number of state variables |
| `n_reachable_states` | int | Reachable state count |
| `n_transitions` | int | Reachable edge count |
| `counterexample` | list[object] \| null | Shortest violating trace: `{label, state}` per step |
| `counterexample_length` | int | Steps in the trace (0 if none) |
| `has_fixed_twin` | bool | Whether a repaired variant exists |
| `fixed_twin_holds` | bool \| null | Whether the repair actually removes the violation |
| `citation` | string \| null | Publication, where the finding is published |
| `known_finding` | string \| null | One-line description of the published finding |

Corpus totals: **67 reachable states** and **83 transitions** across the 15 machines; 2 rows carry a
counterexample; 2 carry a repaired twin, and both twins verify.

## Two difficulty modes

- **`model`** — the full transition table is in the prompt. No protocol knowledge needed; isolates
  formal reasoning.
- **`spec`** — only the standards clause and a description of the procedure. The model must know or
  infer the behaviour. This is the mode corresponding to what a security researcher actually does.

Regenerate either: `python load_dataset.py --regenerate --mode spec`.

## Usage

```python
# No dependencies
from load_dataset import load, stats
rows = load()
stats()          # {'n_rows': 15, 'n_violated': 2, 'trivial_always_safe_accuracy': 0.8667, ...}

# Or as a datasets.Dataset
from load_dataset import load_hf
ds = load_hf()
print(ds[0]["prompt"])
```

```bash
python load_dataset.py --stats        # summary counts
python load_dataset.py --regenerate   # rebuild from the package, so data cannot drift from code
```

Scoring — including trace replay — needs the package, because a trace only means something when
replayed against the real model:

```bash
pip install protocol-bench
protocol-bench prompts --mode model -o prompts.json
# ... run your model, save {task_id: completion} to completions.json ...
protocol-bench score-completions completions.json
```

Nothing but the standard library comes with it: `protocol-bench` depends only on
[`minicheck`](https://pypi.org/project/minicheck/), which itself has no required dependencies.

## Provenance

Rows are generated by `protocol_bench.export.export_rows()` from the same finite-state models the
package ships and the test suite checks. Nothing in this file is hand-written:

- `n_reachable_states`, `n_transitions`, and `transitions` come from exhaustive reachability;
- `counterexample` is the shortest violating trace found by breadth-first search;
- `fixed_twin_holds` is the verdict on the repaired model;
- `label` is cross-checked against exhaustive reachability by a test, so a label cannot drift away
  from its model.

A further test asserts that **the committed JSONL is byte-equal to what the package generates**, and
another asserts that **every counterexample in this file replays against its own model**.

## The negative control, which you can run

A benchmark whose labels are 13 safe and 2 violated can be gamed by answering "safe" every time.
That is not a hypothetical here — it is a shipped baseline, so the floor is measurable rather than
argued:

```bash
pip install protocol-bench
protocol-bench run always-safe
```

    recall on violated         0.000
    recall on safe             1.000
    detections claimed         0
    valid counterexamples      0
    TP 0  FP 0  FN 2  TN 13

**0.867 plain accuracy, 0.500 balanced accuracy, and nothing detected.** A submission reporting
0.867 accuracy has matched a constant. This is why the headline metric is balanced accuracy and why
a detection is credited only when its counterexample replays.

## Regenerating this file, exactly

```bash
pip install protocol-bench
python -c "from protocol_bench.export import export_jsonl; export_jsonl('protocol_bench.jsonl')"
```

    sha256  a147f0e1871ddb80eadef51023223b85890c45bf2b4040769312532284ddb7a3   protocol_bench.jsonl

Checked on 2026-09-04: the bytes that command writes are identical to the file published here and
to the copy in the package repository. If your hash differs, the package version differs — say so
rather than assuming this file drifted.

## Labels, and one deliberate open question

`KNOWN_COUNTEREXAMPLE` means the violation is published and cited. The single instance is the WPA2
4-way handshake — **KRACK** (Vanhoef & Piessens, ACM CCS 2017, CVE-2017-13077…13088).

`CANDIDATE_COUNTEREXAMPLE` means the property fails and **no published citation was found**. It is
labelled unconfirmed on purpose, and it is a genuine open question posed publicly: if you can cite
it, or show the model is wrong, please say so.

## Limitations

These are **models of published procedures**, not the standards themselves and not implementations.
`PROVEN_SAFE` means the property holds over the modelled state space — not that any shipping product
is secure. Abstractions hide things.

The set is small (15 rows) and drawn from one modelling effort, so a system tuned on it will overfit
quickly. Treat per-task outcomes as the primary result and the aggregate as a summary. Two further
procedures exist in the source corpus and are withheld.

Replay validation checks that a trace is a genuine execution reaching a violating state; it does not
check that the trace is the *explanation* a human would give.

## Licence and attribution

MIT, for the code and the task metadata. The KRACK finding belongs to Vanhoef & Piessens; this
dataset reproduces it and does not claim it. Specification clauses are cited, not reproduced.

## Citation

```bibtex
@misc{protocolbench2026,
  title  = {Protocol-Bench: ground-truth safety verdicts for published IEEE 802.11 and 3GPP procedures},
  year   = {2026},
  note   = {Counterexamples are machine-validated by replay against the model.}
}
```
