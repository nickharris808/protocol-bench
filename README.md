# protocol-bench

[![install](https://img.shields.io/badge/install-from%20GitHub-blue)](https://github.com/nickharris808/protocol-bench#install)
[![CI](https://img.shields.io/badge/ci-passing-brightgreen)](https://github.com/nickharris808/protocol-bench/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-123%20passing-brightgreen)](tests/)
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
# from GitHub (PyPI release pending)
pip install "protocol-bench @ git+https://github.com/nickharris808/protocol-bench.git"
```

> `pip install protocol-bench` does not work yet — the package is not on PyPI. Install from GitHub
> as shown above; that pulls in `minicheck` automatically. `python build_pypi.py` produces a
> PyPI-uploadable artifact for when both packages are published (PyPI rejects the direct dependency
> reference this package uses to stay installable without an index).

This pulls in [`minicheck`](https://github.com/nickharris808/minicheck), the model checker the task models are written against.

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
| `always-violated` | 0.000 | 0.000 | 15 | **0** |

Read those three rows together, because they are the argument for the metric:

- **`always-safe` gets 86.7% accuracy** by guessing. Most published procedures are safe, so plain
  accuracy is nearly uninformative here. That is why the headline is **balanced accuracy**, on which
  the same guesser scores 0.500.
- **`always-violated` claims 15 detections and validates zero, and scores 0.000.** Claiming
  everything is broken is not a finding: the 13 safe tasks become false positives, and the 2 real
  ones earn nothing because no trace replays. The `valid CEX` column is what separates a detector
  from a guesser.
- **`bfs` is the ceiling, not a competitor.** It is sound and complete over a finite model that has
  already been formalised for it. The open problem is doing this *from the spec text*.

A submission that answers every task correctly but fabricates its traces scores **0.500** — the same
as the trivial guesser, which is what it is. See [Honest scope](#honest-scope).

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

## Honest scope

**Scoring credits a detection only when its trace replays.** For a task that really is violated:

| submission | scored as |
|---|---|
| `violated` + a trace that replays | true positive |
| `violated` + a trace that does not replay | false negative |
| `violated` + no trace | false negative |
| not `violated` | false negative |

For a safe task, *any* violation claim is a false positive. `accuracy_ignoring_replay` is reported
alongside so the gap between what a submission asserted and what it demonstrated stays visible, and
`unreplayed_claims` counts the difference.

This matters because guessing is easy here. "The WPA2 four-way handshake" sits next to "vulnerable"
in every training corpus, so a model can be right about it having done no reasoning at all. Under
verdict-only scoring, a submission that answers every task correctly and fabricates every trace
scores **1.0**. Under replay-gated scoring it scores **0.5** — exactly the trivial always-safe
guesser, which is what it is.

**What a result proves.** That a submission produced a counterexample which replays against the
published model: it starts at the initial state, every step is a real transition, and the final state
violates the named property.

**What it does not prove.**

- Nothing about shipping products. These are **models of published procedures**, not the standards
  themselves and not implementations. `PROVEN_SAFE` means the property holds over the modelled state
  space; a model abstracts, and an abstraction can hide a real defect.
- Nothing statistically robust. 15 tasks, 2 of them violated. The set is deliberately imbalanced
  because the published-procedure population is. **Treat per-task outcomes as the primary result and
  any aggregate as a summary** — a single task flipping moves balanced accuracy by 0.25.
- Nothing about generalisation. A model that has memorised these 15 will score well.

**A scoring bug shipped in 1.0.0 and is fixed here (1.1.0).** Replay validation was computed and then
ignored by the headline metric. See [SECURITY-ADVISORY.md](SECURITY-ADVISORY.md).

## Where this came from, and what is not here

These 15 tasks are the publicly-reproducible slice of a larger counterexample corpus. What is not in
this package: the *foundry* that generates and classifies new procedures, the design-around
tournament that scores how hard a finding is to engineer around, and the standards-essentiality
tooling. The benchmark is MIT and stays that way; the generator is the commercial offering.

## API and CLI reference

### CLI

| Command | What it does |
|---|---|
| `protocol-bench info` | dataset version and task counts |
| `protocol-bench list` | every task with its label |
| `protocol-bench run BASELINE` | run a built-in baseline (`bfs`, `always-safe`, `always-violated`) and score it |
| `protocol-bench score FILE` | score a submission JSON file |
| `protocol-bench prompts` | emit one prompt per task for a language model |
| `protocol-bench score-completions FILE` | score raw model replies (`{task_id: "reply text"}`) |
| `protocol-bench export` | export the task set as JSON Lines |

Common flags: `-o FILE` to write output, `--json` for machine-readable results, and
`--mode {model,spec}` on `prompts` and `export` to choose the difficulty.

### Python API

| Name | What it does |
|---|---|
| `load_tasks()` | every `Task` in the benchmark |
| `Task.build()` | the `minicheck.Protocol` for that task |
| `Task.build_fixed()` | the repaired twin, where one exists (`Task.fixed_builder`) |
| `Task.property` | the name of the safety property being checked |
| `Task.is_violated` | ground truth |
| `Task.label` | `KNOWN_COUNTEREXAMPLE`, `CANDIDATE_COUNTEREXAMPLE`, or `PROVEN_SAFE` |
| `score(submission, tasks=None)` | the full report (see below) |
| `validate_trace(task, trace)` | replay one claimed counterexample; returns `{valid, reason}` |
| `build_prompt(task, mode)` | the prompt text for a task |
| `score_completions(completions)` | parse raw replies, then score |
| `BASELINES` | name → callable for the built-in baselines |

### What `score()` returns

| Key | Meaning |
|---|---|
| `balanced_accuracy` | **headline.** Mean of per-class recall, computed from credited detections |
| `accuracy` | plain accuracy, also replay-gated |
| `accuracy_ignoring_replay` | what the score would be if claims were taken at face value |
| `unreplayed_claims` | detections claimed whose trace did not replay |
| `valid_counterexamples` | detections whose trace did replay |
| `true_positives` / `false_positives` / `false_negatives` / `true_negatives` | the confusion matrix; always sums to `n_tasks` |
| `trivial_always_safe_accuracy` | what guessing "safe" everywhere scores |
| `per_task` | one row per task: `predicted_violated`, `credited_detection`, `outcome`, `trace` |

A large gap between `accuracy_ignoring_replay` and `accuracy` means the submission asserted more
than it demonstrated.

## Troubleshooting

**My submission scored 0 true positives but I got the verdicts right.** A detection is credited only
when its trace replays. Check `unreplayed_claims` and the per-task `trace.reason`, which names the
first thing that failed: wrong initial state, a step that is not a transition, or a final state that
does not violate the property.

**`trace does not start at the initial state`.** The first entry must be the model's initial state
exactly. Get it from `task.build().initial`.

**`step i -> i+1 is not a transition of the model`.** The trace jumps. Every consecutive pair must be
connected by a real transition; check against `model.transitions(state)`.

**`final state does not violate the property`.** The trace is a legal path that stops too early. It
must end *in* the violating state, not one step before it.

**`a step does not name the model's fields`.** Each entry is `{"state": {field: value, ...}}` with
every field present, or a bare list in field order.

**`n_unparseable` is high.** The model replied in prose. The parser accepts bare JSON, fenced blocks,
and JSON embedded in text, but the object must contain a `violated` key. Unparseable replies are
counted separately from cautious ones, so the two are never confused.

**`balanced_accuracy` is 0.5 and I thought I did well.** 0.5 is the trivial guesser. If
`accuracy_ignoring_replay` is much higher, the submission is asserting more than it can demonstrate.

**A task is labelled `CANDIDATE_COUNTEREXAMPLE`.** The property fails and no published citation was
found. It is unconfirmed on purpose — if you can cite it, or show the model is wrong, please open an
issue.

## Performance

Measured: `load_tasks()` takes about **4 ms** on the first call, which parses and builds all 15
models, and about **0.1 ms** on subsequent calls. A full `score()` with replay
validation of every trace takes about **0.1 ms**. `parse_response` is about **3 µs** per reply.
Nothing here is a bottleneck and nothing has been optimised for speed beyond fixing one genuine
defect — the reply parser was accidentally cubic in the reply length and is now linear.

## Tests

```
pip install -e ".[test]" && pytest
```

123 tests. Fifteen of them re-derive every ground-truth label by exhaustive reachability, so the
labels cannot drift away from the shipped models; the rest cover trace-validation failure modes, the
prompt builders (including that the prompt never leaks the answer), the reply parser, and the CLI.

## The portfolio

Five small, independently useful tools built around one idea: **a verdict you cannot check is not a verdict.**

| | |
|---|---|
| [`minicheck`](https://github.com/nickharris808/minicheck) | An explicit-state model checker in ~1290 lines, with a CLI. Shortest counterexamples, no required dependencies. |
| [`protocol-bench`](https://github.com/nickharris808/protocol-bench) ← *you are here* | 15 published IEEE 802.11 / 3GPP procedures with ground truth. A claimed detection must **replay**. |
| [`minicheck-mcp`](https://github.com/nickharris808/minicheck-mcp) | The checker as an **MCP server** — let an agent verify a state machine instead of guessing. |
| [`polyfrac`](https://github.com/nickharris808/polyfrac) | Exact polynomial + rational-function arithmetic over ℚ with Sturm real-root counting. Zero deps. |
| [`failclosed`](https://github.com/nickharris808/failclosed) | Default-deny ASGI middleware: a gated endpoint succeeds only on an affirmative verdict. |
| [`protocol-bench-action`](https://github.com/nickharris808/protocol-bench-action) | Score a submission in CI and fail the build if a claimed detection cannot be proved |

Try it in your browser: **[live demo](https://huggingface.co/spaces/nickh007/protocol-bench-demo)** · Ground-truth tasks: **[dataset](https://huggingface.co/datasets/nickh007/protocol-bench)**

### The commercial offering

These are the engine. What is **not** open source is what makes it useful at scale: the maintained
hazard-property corpora, composition analysis that finds hazards existing only when two components
are combined, the trust-model sensitivity sweep, and the evidence trail that makes a verdict auditable
after the fact. The tools above are MIT and stay that way.

## Licence

MIT for the code and the task metadata. See `LICENSE`. Citations name their original authors; the
KRACK finding is Vanhoef & Piessens', not ours — this package reproduces it.
