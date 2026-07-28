# protocol-bench

[![PyPI](https://img.shields.io/badge/pypi-protocol--bench-blue)](https://pypi.org/project/protocol-bench/)
[![CI](https://img.shields.io/badge/ci-passing-brightgreen)](../.github/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-61%20passing-brightgreen)](tests/)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![tasks](https://img.shields.io/badge/tasks-15-orange)

**Ground-truth safety verdicts for 15 published IEEE 802.11 and 3GPP procedures — where a claimed
detection has to replay before it counts.**

## Why this exists

Two problems with how protocol reasoning gets evaluated. First, every paper builds its own models, so
no two results are comparable. Second, and worse for language models: a verdict is separable from the
reasoning that should justify it. "The WPA2 four-way handshake" is strongly associated with
"vulnerable" in any training corpus, so a model can be right about it having done no reasoning at all
— and verdict-only scoring cannot tell that apart from understanding.

Requiring a **counterexample that replays** closes both gaps. The trace must start at the initial
state, move only along real transitions, and end in a genuinely violating state. Recalling a CVE does
not produce one; reasoning about the state machine does.

Protocol-verification papers each roll their own models, so results are not comparable. This is a
fixed, versioned task set: fifteen real procedures from published standards, each with a named safety
property and a ground-truth label. Two of them genuinely violate their property; thirteen do not.

The interesting bit is the scoring. Predicting "violated" is cheap. Supplying a **counterexample that
replays against the model** is not — so the benchmark validates every trace you submit: it must start
at the initial state, every step must be a real transition, and the final state must actually violate
the property.

## Install

```
pip install protocol-bench
```

This pulls in [`minicheck`](../minicheck), the model checker the task models are written against.

## 30-second quickstart

```console
$ protocol-bench run bfs
baseline: bfs
  tasks                      15
  balanced accuracy          1.000   <- headline
  accuracy                   1.000
  (trivial always-safe acc.  0.867)
  recall on violated         1.000
  recall on safe             1.000
  detections claimed         2
  valid counterexamples      2
  TP 2  FP 0  FN 0  TN 13
```

```python
from protocol_bench import load_tasks, score

tasks = load_tasks()
score({t.id: {"violated": False} for t in tasks})["balanced_accuracy"]   # 0.5
```

## Baselines (reproduce with `protocol-bench run <name>`)

| Baseline | Balanced acc. | Accuracy | Detections | Valid CEX |
|---|---|---|---|---|
| `bfs` — exhaustive reachability | **1.000** | 1.000 | 2 | **2** |
| `always-safe` | 0.500 | **0.867** | 0 | 0 |
| `always-violated` | 0.500 | 0.133 | 15 | **0** |

Read those three rows together, because they are the argument for the metric:

- **`always-safe` gets 86.7% accuracy** by guessing. Most published procedures are safe, so plain
  accuracy is nearly uninformative here. That is why the headline is **balanced accuracy**, on which
  the same guesser scores 0.500.
- **`always-violated` claims 15 detections and validates zero.** Claiming everything is broken is not
  a finding. The `valid CEX` column is what separates a detector from a guesser.
- **`bfs` is the ceiling, not a competitor.** It is sound and complete over a finite model that has
  already been formalised for it. The open problem is doing this *from the spec text*.

## The task set

| Label | Count | Meaning |
|---|---|---|
| `KNOWN_COUNTEREXAMPLE` | 1 | Violated, with a published citation |
| `CANDIDATE_COUNTEREXAMPLE` | 1 | Violated, **uncited** — unconfirmed, needs expert review |
| `PROVEN_SAFE` | 13 | Holds over all reachable states |

Eight IEEE 802.11 procedures (4-way handshake, fast BSS transition, MLO TID-to-link, block ack,
target wake time, U-APSD, SA query, FILS) and seven 3GPP procedures (RRC state machine, PDCP
reordering, RLC AM retransmission, DRX timers, RACH contention, beam failure recovery, Xn handover).

The `KNOWN` entry is the WPA2 4-way handshake — **KRACK** (Vanhoef & Piessens, CCS 2017,
CVE-2017-13077…13088). Its model reproduces the key reinstallation that resets the nonce, and the
benchmark ships the metadata-gated `_fixed` twin so you can confirm the counterexample is *removable*
rather than a modelling artefact.

`CANDIDATE` is deliberate honesty, not a claim: the property fails and no published citation was
found, so it is labelled unconfirmed. If you can cite it — or show the model is wrong — please open an
issue. That is a real open question, posed publicly.

## Evaluating a language model

The benchmark ships a prompt builder, a tolerant reply parser, and scoring — no network, no model
calls. You supply the completions.

```bash
protocol-bench prompts --mode model -o prompts.json   # full state machine in the prompt
protocol-bench prompts --mode spec  -o prompts.json   # only the clause + description (hard mode)
# ... run your model, save {task_id: completion_text} to completions.json ...
protocol-bench score-completions completions.json
```

Two difficulty modes:

- **`model`** — the transition table is in the prompt. No protocol knowledge needed; this isolates
  formal reasoning.
- **`spec`** — only the standards clause and a description. The model must know or infer the
  behaviour. This is the mode that corresponds to what a security researcher actually does.

The parser handles bare JSON, fenced code blocks, and JSON embedded in prose. A reply it cannot parse
is scored as *no detection* and counted separately as `n_unparseable`, so "answered in prose" is
distinguishable from "answered safe".

The reason to use this rather than verdict-only scoring: a model can name the WPA2 handshake as
vulnerable from memory without reasoning about the state machine at all. Requiring a replaying trace
separates the two.

```python
from protocol_bench import build_prompt, load_tasks, score_completions

prompts = {t.id: build_prompt(t, "model") for t in load_tasks()}
completions = {tid: my_model(p) for tid, p in prompts.items()}
res = score_completions(completions)
res["valid_counterexamples"], res["n_unparseable"]
```

## Dataset export

```bash
protocol-bench export -o protocol_bench.jsonl --mode model
```

One self-contained row per task: prompt, state-machine rendering, label, binary target, citation. A
dataset card is in [`dataset/`](dataset). Note that scoring a *trace* still needs this package,
because a trace only means something when replayed against the real model.

## Worked example — submit your own detector

A submission maps task id to a prediction. `violated` is required; `trace` is optional and is what
earns the detection credit.

```python
import json
from protocol_bench import load_tasks, score

submission = {}
for task in load_tasks():
    model = task.build()                 # a minicheck.Protocol
    verdict, trace = my_analyser(model, task.property)
    submission[task.id] = {"violated": verdict, "trace": trace}

json.dump(submission, open("submission.json", "w"), default=str)
```

```console
$ protocol-bench score submission.json
```

A trace that does not replay is reported with the reason it failed:

```python
>>> from protocol_bench import load_tasks, validate_trace
>>> t = next(t for t in load_tasks() if t.id == "ieee_4way_handshake_krack")
>>> validate_trace(t, [{"state": {"bogus": 1}}])
{'supplied': True, 'valid': False,
 'reason': "a step does not name the model's fields (...)"}
```

## Scoring in full

| Field | Meaning |
|---|---|
| `balanced_accuracy` | **Headline.** Mean of per-class recall; 0.5 for any constant guesser |
| `accuracy` | Plain accuracy, reported next to the trivial baseline so it cannot be quoted alone |
| `valid_counterexamples` | Detections whose trace replayed against the model |
| `detections_claimed` | Detections asserted, replayed or not |
| `recall_violated` / `recall_safe` | Per-class recall |
| `per_task` | Row per task: outcome and the trace-validation verdict with its reason |

## Scope and honesty

These are **models of published procedures**, not the standards themselves and not implementations.
A `PROVEN_SAFE` label means the property holds over the modelled state space — it is not a claim that
any shipping product is secure. A model abstracts, and an abstraction can hide a real defect.

The task set is small and deliberately imbalanced, because that is what the published-procedure
population actually looks like. Treat per-task outcomes as the primary result and the aggregate as a
summary.

## Where this came from, and what is not here

These 15 tasks are the publicly-reproducible slice of a larger counterexample corpus. What is not in
this package: the *foundry* that generates and classifies new procedures, the design-around
tournament that scores how hard a finding is to engineer around, and the standards-essentiality
tooling. The benchmark is MIT and stays that way; the generator is the commercial offering.

## Related

- [`minicheck`](../minicheck) — the model checker the models are written against, and the `bfs` baseline.

## Tests

```
pip install -e ".[test]" && pytest
```

61 tests. Fifteen of them re-derive every ground-truth label by exhaustive reachability, so the
labels cannot drift away from the shipped models; the rest cover trace-validation failure modes, the
prompt builders (including that the prompt never leaks the answer), the reply parser, and the CLI.

## Licence

MIT for the code and the task metadata. See `LICENSE`. Citations name their original authors; the
KRACK finding is Vanhoef & Piessens', not ours — this package reproduces it.
