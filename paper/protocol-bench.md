# Protocol-Bench: counterexamples that have to replay

**Abstract.** We present Protocol-Bench, a benchmark of 15 published IEEE 802.11 and 3GPP procedures
with ground-truth safety verdicts, in which a claimed detection is only credited if it is accompanied
by a counterexample trace that mechanically replays against the model. We argue that verdict-only
scoring is inadequate for protocol-reasoning evaluation on two grounds: the label distribution of
published procedures is heavily skewed toward "safe", making plain accuracy nearly uninformative; and
a binary verdict is separable from the reasoning that should justify it, so a model can be right for
no reason. Replay-validated counterexamples address both. We report reference baselines, including
two trivial ones that exist to bound the metric from below.

---

## 1. Motivation

Work on protocol verification and on protocol reasoning by language models shares a methodological
weakness: each paper builds its own models, so results are not comparable, and evaluation is usually
by verdict. A verdict is cheap. On a two-class problem an uninformed guess is right half the time,
and on a skewed one a constant answer does considerably better than that.

The second problem is subtler and matters more for language models. A verdict can be produced by
pattern-matching a procedure name against training data — "the WPA2 four-way handshake" is strongly
associated with "vulnerable" — without any reasoning about the state machine in front of the model.
Such an answer is correct and worthless, and verdict-only scoring cannot distinguish it from
understanding.

## 2. The task

Each task is a triple: a finite-state model of a published procedure, a named safety property, and a
ground-truth label in `{KNOWN_COUNTEREXAMPLE, CANDIDATE_COUNTEREXAMPLE, PROVEN_SAFE}`. A system under
evaluation returns, per task, a boolean `violated` and optionally a `trace`.

The label taxonomy carries an honesty constraint that is enforced mechanically:
`KNOWN_COUNTEREXAMPLE` requires a citation; `CANDIDATE_COUNTEREXAMPLE` requires the *absence* of one
and is explicitly marked unconfirmed. We prefer publishing an open question to silently promoting a
model-checking artefact into a claimed vulnerability.

Two prompt modes are provided. In **model** mode the full transition table is rendered into the
prompt, so no protocol knowledge is required and the task isolates formal reasoning. In **spec** mode
only the standards clause and a description of the procedure are given, and the system must know or
infer the behaviour. Mode selection is the main difficulty lever.

## 3. Replay validation

Given a claimed trace, the harness replays it against the model and requires, in order: the trace is
non-empty; its first state is the model's initial state; every consecutive pair is a transition of
the model; and the final state falsifies the property. Failure at any step returns a machine-readable
reason.

This is the design decision the benchmark rests on. It is cheap to assert that a protocol is broken
and expensive to demonstrate it, and the gap between those two costs is exactly the quantity worth
measuring. A trace that does not replay earns nothing, so `detections_claimed` and
`valid_counterexamples` are reported as separate columns and their divergence is diagnostic.

## 4. Metric

We report **balanced accuracy** — the unweighted mean of per-class recall — as the headline, with
plain accuracy reported beside the accuracy of a constant "safe" predictor so the two cannot be
confused. We additionally report `valid_counterexamples`.

The choice follows from the distribution. Of 15 tasks, 13 are safe; a constant "safe" predictor
therefore achieves 0.867 accuracy and 0.500 balanced accuracy. Reporting accuracy alone would make a
degenerate system look strong.

## 5. Baselines

| Baseline | Balanced acc. | Accuracy | Detections | Valid CEX |
|---|---|---|---|---|
| Exhaustive reachability | 1.000 | 1.000 | 2 | 2 |
| Constant "safe" | 0.500 | 0.867 | 0 | 0 |
| Constant "violated" | 0.500 | 0.133 | 15 | 0 |

The exhaustive baseline is sound and complete over the finite model and is included as a **ceiling,
not a competitor**: it operates on a model that has already been formalised. The open problem is
`spec` mode, where the formalisation step is the work.

The two constant baselines are the reason the metric is shaped as it is. "Constant violated" attains
perfect recall on the violated class, claims 15 detections, and validates none — a system that
asserts everything is broken has produced no findings.

## 6. Limitations

The task set is small (15) and drawn from one modelling effort, so a system tuned on it would overfit
quickly; per-task outcomes should be treated as the primary result. The models are abstractions of
published procedures, not implementations: `PROVEN_SAFE` means the property holds over the modelled
state space, and an abstraction can hide a real defect. Two further procedures exist in the source
corpus and are withheld. Replay validation checks that a trace is a genuine execution reaching a
violating state; it does not check that the trace is the *explanation* a human would give.

## 7. Availability

`pip install protocol-bench`. The harness, the models, the ground truth, and the scoring code are
MIT-licensed. Every ground-truth label is re-derived from the shipped model by exhaustive
reachability in the test suite, so labels and models cannot drift apart.

## Reproducibility appendix

```bash
pip install "protocol-bench @ git+https://github.com/nickharris808/protocol-bench.git"
# `pip install protocol-bench` does not work yet — the package is not on PyPI.
protocol-bench run bfs              # 1.000 balanced accuracy, 2/2 counterexamples replay
protocol-bench run always-safe      # 0.500 balanced accuracy, 0.867 plain accuracy
protocol-bench run always-violated  # 0.500 balanced accuracy, 15 claimed, 0 validated
protocol-bench list                 # the task set and its labels
```

Language-model evaluation:

```bash
protocol-bench prompts --mode model -o prompts.json   # or --mode spec
# run your model over prompts.json, save {task_id: completion_text}
protocol-bench score-completions completions.json
```

All baselines are deterministic; the numbers in §5 are reproduced by the commands above. The test
suite (`pytest`) re-derives every label and includes the trace-validation failure modes as explicit
cases.

## Attribution

The key-reinstallation finding modelled in `ieee_4way_handshake_krack` is due to Vanhoef and Piessens
(ACM CCS 2017; CVE-2017-13077 through CVE-2017-13088). This benchmark reproduces it and does not
claim it. Specification clauses are cited, not reproduced.
