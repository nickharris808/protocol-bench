# Contributing to protocol-bench

A benchmark is only worth what its ground truth is worth. That shapes what changes are easy to accept.

## Ground rules

1. **Labels are derived, never asserted.** Every ground-truth label is re-checked against the shipped
   model by exhaustive reachability in the test suite. A pull request that changes a label without
   changing the model — or vice versa — will fail CI, and that is intended.
2. **`KNOWN` requires a citation; `CANDIDATE` requires the absence of one.** That distinction is the
   honesty of the taxonomy and it is enforced by a test. If you can cite the CANDIDATE entry, that is
   a very welcome pull request: change the label AND add the citation together.
3. **A new task needs a model, a property, a label, and — if violated — a fixed twin.** A
   counterexample nobody can remove is usually a modelling error rather than a finding.

## Getting set up

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Pull requests

- Add a test that fails before your change and passes after. Tests live in `tests/`.
- Keep the public API in `__all__` explicit; anything not listed there is internal.
- Do not change the scoring weights to make a submission look better. If the metric is wrong, argue
  about the metric in an issue first.
- Sign-off by [DCO](https://developercertificate.org/) (`git commit -s`). There is no CLA.

## Disputing a label

The most valuable contribution here is showing that a label is wrong — that a `PROVEN_SAFE` model
abstracts away a real defect, or that the `CANDIDATE` entry is either citable or a modelling error.
Please include the concrete trace or the citation, so it can go straight into the test suite.
