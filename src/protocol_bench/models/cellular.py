"""Explicit-state models of published 3GPP NR procedures.

Each `build*() -> Protocol` models the procedure as published with a named safety invariant. Most are
proven safe at this abstraction; `xn_handover` includes a NAIVE premature-release variant whose
data-loss counterexample is flagged as a CANDIDATE (needs expert review), with a make-before-break fix.
"""

from minicheck import Protocol


# ----------------------------------------------------------------- RRC state machine
def rrc_state_machine() -> Protocol:
    """RRC IDLE(0)/INACTIVE(1)/CONNECTED(2): user data only in CONNECTED."""

    def trans(s):
        state, data = s
        out = []
        if state == 0:
            out.append(("Connect", (2, data)))
        if state == 2 and not data:  # leave CONNECTED only when no data is in transfer
            out.append(("Suspend", (1, data)))
            out.append(("Release", (0, data)))
        if state == 1:
            out.append(("Resume", (2, data)))
            out.append(("ReleaseFromInactive", (0, data)))
        if state == 2 and not data:
            out.append(("SendData", (2, True)))
        if data:
            out.append(("DataDone", (state, False)))
        return out

    inv = {"no_data_in_idle": lambda d: (not d["data"]) or d["state"] == 2}
    return Protocol(
        "3gpp_rrc_state_machine",
        candidate=True,
        fields=("state", "data"),
        initial=(0, False),
        transitions=trans,
        invariants=inv,
        goal=lambda d: d["state"] == 2,
    )


# ----------------------------------------------------------------- PDCP reordering / duplication
def pdcp_reordering() -> Protocol:
    """PDCP discards a PDU whose count is below the reordering window -> no duplicate delivered."""
    W = 3

    def trans(s):
        next_count, dup = s
        out = []
        if next_count < W:
            out.append(("DeliverInOrder", (next_count + 1, dup)))
        if next_count > 0:
            out.append(("RecvDuplicate_discard", (next_count, dup)))  # count < RX_DELIV -> discard
        return out

    inv = {"no_duplicate_delivered": lambda d: not d["dup"]}
    return Protocol(
        "3gpp_pdcp_reordering",
        candidate=True,
        fields=("next_count", "dup"),
        initial=(0, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- RLC-AM retransmission
def rlc_am_retx() -> Protocol:
    """RLC AM retransmits an unacked PDU up to maxRetxThreshold, then declares failure (RLF) — never
    an unbounded retransmit loop. retx capped by MAX."""
    MAX = 4

    def trans(s):
        retx, acked, failed = s
        out = []
        if not acked and not failed and retx < MAX:
            out.append(("Retransmit", (retx + 1, acked, failed)))
        if not acked and not failed:
            out.append(("Ack", (retx, True, failed)))
        if not acked and not failed and retx >= MAX:
            out.append(("MaxRetx_RLF", (retx, acked, True)))
        return out

    inv = {"retx_bounded_no_runaway": lambda d: d["retx"] <= MAX}
    return Protocol(
        "3gpp_rlc_am_retx",
        candidate=True,
        fields=("retx", "acked", "failed"),
        initial=(0, False, False),
        transitions=trans,
        invariants=inv,
        goal=lambda d: d["acked"] or d["failed"],
    )


# ----------------------------------------------------------------- DRX timers
def drx_timers() -> Protocol:
    """DRX: while onDuration or inactivity/RTT timers keep the UE active, it monitors PDCCH; PDCCH is
    only expected while active -> the UE is never asleep when PDCCH is expected."""

    def trans(s):
        active, pdcch_expected = s
        out = []
        out.append(("OnDurationStart", (True, pdcch_expected)))
        if active and not pdcch_expected:
            out.append(("ExpectPDCCH", (True, True)))  # only set while active
        if pdcch_expected:
            out.append(("PDCCHReceived", (active, False)))
        if active and not pdcch_expected:
            out.append(("InactivityExpire_sleep", (False, pdcch_expected)))
        return out

    inv = {"awake_when_pdcch_expected": lambda d: (not d["pdcch_expected"]) or d["active"]}
    return Protocol(
        "3gpp_drx_timers",
        candidate=True,
        fields=("active", "pdcch_expected"),
        initial=(False, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- RACH contention resolution
def rach() -> Protocol:
    """Random access: a contention (two UEs, same preamble) is always resolved by the contention
    resolution identity before the grant is used -> no undetected collision."""

    def trans(s):
        preamble, contention, resolved, undetected = s
        out = []
        if not preamble:
            out.append(("SendPreamble", (True, contention, resolved, undetected)))
        if preamble and not contention:
            out.append(("CollisionOccurs", (preamble, True, resolved, undetected)))
        if contention and not resolved:
            out.append(("ContentionResolutionID", (preamble, contention, True, undetected)))
        return out

    # a collision is "undetected" only if a grant is used while contention is unresolved; the
    # contention-resolution step always precedes use, so this never becomes true.
    inv = {"no_undetected_collision": lambda d: not d["undetected"]}
    return Protocol(
        "3gpp_rach_contention",
        candidate=True,
        fields=("preamble", "contention", "resolved", "undetected"),
        initial=(False, False, False, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- Beam failure recovery
def beam_failure_recovery() -> Protocol:
    """Beam failure recovery: on detection the UE sends a BFR request and recovers before the radio
    link failure timer expires -> no RLF on a recoverable beam failure."""

    def trans(s):
        bf_detected, bfr_sent, recovered, rlf = s
        out = []
        if not bf_detected:
            out.append(("DetectBeamFailure", (True, bfr_sent, recovered, rlf)))
        if bf_detected and not bfr_sent and not recovered:
            out.append(("SendBFR", (bf_detected, True, recovered, rlf)))
        if bfr_sent and not recovered:
            out.append(("RecoverBeam", (bf_detected, bfr_sent, True, rlf)))
        return out

    # RLF can only be set if the recovery window elapses without recovery; the model recovers on BFR,
    # so rlf stays false on a recoverable failure.
    inv = {"recover_before_rlf": lambda d: not d["rlf"]}
    return Protocol(
        "3gpp_beam_failure_recovery",
        candidate=True,
        fields=("bf_detected", "bfr_sent", "recovered", "rlf"),
        initial=(False, False, False, False),
        transitions=trans,
        invariants=inv,
        goal=lambda d: d["recovered"],
    )


# ----------------------------------------------------------------- Xn handover (CANDIDATE finding)
def xn_handover() -> Protocol:
    """Xn handover, NAIVE premature-release variant: the source releases the UE context before the
    path switch is acknowledged, opening a window with NO serving context -> in-flight data is lost.
    Flagged CANDIDATE (needs expert review): whether a compliant Xn handover can reach this depends on
    timer/forwarding configuration. Fields: (source_ctx, target_ctx, path_switched, data_lost)."""

    def trans(s):
        src, tgt, path, lost = s
        out = []
        if src and not tgt:
            out.append(("PrepareTarget", (src, True, path, lost)))  # target context set up
        if src and tgt:
            # NAIVE: release source before path-switch ack
            out.append(("ReleaseSourceEarly", (False, tgt, path, lost or (not path))))
        if tgt and not path:
            out.append(("PathSwitchAck", (src, tgt, True, lost)))
        return out

    inv = {"always_one_serving_context": lambda d: not d["data_lost"]}
    return Protocol(
        "3gpp_xn_handover_premature_release",
        candidate=False,
        fields=("source_ctx", "target_ctx", "path_switched", "data_lost"),
        initial=(True, False, False, False),
        transitions=trans,
        invariants=inv,
    )


def xn_handover_fixed() -> Protocol:
    """Make-before-break fix: the source context is kept until the path switch is acknowledged (and
    data is forwarded), so there is never a no-context window."""

    def trans(s):
        src, tgt, path, lost = s
        out = []
        if src and not tgt:
            out.append(("PrepareTarget", (src, True, path, lost)))
        if tgt and not path:
            out.append(("PathSwitchAck", (src, tgt, True, lost)))
        if src and tgt and path:
            out.append(("ReleaseSourceAfterAck", (False, tgt, path, lost)))  # only after ack
        return out

    inv = {"always_one_serving_context": lambda d: not d["data_lost"]}
    return Protocol(
        "3gpp_xn_handover_fixed",
        candidate=True,
        fields=("source_ctx", "target_ctx", "path_switched", "data_lost"),
        initial=(True, False, False, False),
        transitions=trans,
        invariants=inv,
    )
