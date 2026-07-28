"""Task loading and model construction."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import resources
from typing import Optional

from minicheck import Protocol

from . import models

#: Ground-truth labels.
KNOWN = "KNOWN_COUNTEREXAMPLE"  #: violated, with a published citation
CANDIDATE = "CANDIDATE_COUNTEREXAMPLE"  #: violated, uncited — unconfirmed, needs expert review
SAFE = "PROVEN_SAFE"  #: holds over all reachable states

LABELS = (KNOWN, CANDIDATE, SAFE)


@dataclass(frozen=True)
class Task:
    """One benchmark item: a published procedure, a safety property, and a ground-truth label."""

    id: str
    standards_body: str
    spec_clause: str
    property: str
    module: str
    builder: str
    fixed_builder: Optional[str]
    label: str
    citation: Optional[str]
    known_finding: Optional[str]

    @property
    def is_violated(self) -> bool:
        """Ground truth as a binary: does the property fail on this model?"""
        return self.label in (KNOWN, CANDIDATE)

    def build(self) -> Protocol:
        """The procedure as published."""
        return getattr(getattr(models, self.module), self.builder)()

    def build_fixed(self) -> Optional[Protocol]:
        """The metadata-gated repair, where one exists."""
        if not self.fixed_builder:
            return None
        return getattr(getattr(models, self.module), self.fixed_builder)()


def _raw() -> dict:
    with resources.files("protocol_bench").joinpath("data/ground_truth.json").open() as fh:
        return json.load(fh)


def load_tasks() -> list[Task]:
    """Every benchmark task, in registry order."""
    return [Task(**t) for t in _raw()["tasks"]]


def dataset_info() -> dict:
    """Version and counts, without the task bodies."""
    d = _raw()
    return {k: v for k, v in d.items() if k != "tasks"}


def iter_tasks() -> Iterator[Task]:
    yield from load_tasks()
