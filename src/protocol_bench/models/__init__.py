"""Finite-state models of published IEEE 802.11 and 3GPP procedures.

Each builder returns a `minicheck.Protocol` modelling the procedure AS PUBLISHED. Where a
`*_fixed` twin exists it is the metadata-gated repair, included so that a reported
counterexample can be shown to be removable rather than merely asserted.
"""

from . import cellular, ieee

__all__ = ["ieee", "cellular"]
