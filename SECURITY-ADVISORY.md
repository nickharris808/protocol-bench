# Advisory — replay validation was not wired into the score (protocol-bench 1.0.0)

**Severity:** high for anyone citing a score. **Fixed in:** 1.1.0. **Found by:** the maintainer,
during a hardening audit.

## Summary

The README stated that "a claimed detection has to replay before it counts". It did not. `score()`
computed the confusion matrix from the `violated` flag alone; the replay result was carried in the
per-task report and never consulted by any headline metric.

A submission that answered every task correctly and fabricated every trace scored **balanced accuracy
1.0** — the precise failure the benchmark exists to detect.

## Reproducer (1.0.0)

```python
sub = {t.id: {"violated": t.is_violated, "trace": [{"state": {"TOTALLY": "FAKE"}}]}
       for t in load_tasks()}
score(sub)
# 1.0.0 -> balanced_accuracy 1.0, true_positives 2, valid_counterexamples 0
```

## Fix

A detection is credited only when its trace replays. On 1.1.0 the same submission scores
**balanced accuracy 0.5** — identical to the trivial always-safe guesser. An honest solver that
produces real traces is unaffected and still scores 1.0.

New fields: `unreplayed_claims`, `credited_detection` per task, and `accuracy_ignoring_replay` so the
gap between asserted and demonstrated stays visible.

## Action required

Any score computed with 1.0.0 is not comparable to one from 1.1.0 and should be recomputed. Scores
from submissions that supplied genuine traces are unchanged.
