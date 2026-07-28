"""Explicit-state models of published IEEE 802.11 procedures.

Each `build*() -> Protocol` models the procedure as published, with a named safety invariant. The
4-way handshake reproduces the KNOWN key-reinstallation (KRACK) counterexample; the rest are proven
safe at this abstraction.
"""

from minicheck import Protocol


# ----------------------------------------------------------------- 4-way handshake (KRACK)
def four_way_handshake() -> Protocol:
    """IEEE 802.11i/802.11-2020 4-way handshake, supplicant side, AS PUBLISHED (vulnerable).

    The supplicant installs the PTK on EAPOL-Key msg3 and — per the original state machine — ACCEPTS a
    retransmitted/replayed msg3 and REINSTALLS the PTK, resetting the TX packet-number (nonce). If
    frames were already sent under the PTK, the reset reuses an already-used nonce value with the same
    key. Reproduces Vanhoef & Piessens (CCS 2017) / CVE-2017-13077.
    Fields: (ptk_installed, tx_nonce, nonce_reused). tx_nonce capped at 2 to bound the model."""
    NMAX = 2

    def trans(s):
        installed, nonce, reused = s
        out = []
        if not installed:
            out.append(("InstallPTK_msg3", (True, 0, reused)))  # first install, PN reset to 0
        if installed and nonce < NMAX:
            out.append(("SendEncrypted", (True, nonce + 1, reused)))  # use next packet number
        if installed:
            # retransmitted/replayed msg3 -> REINSTALL: PN reset; reuse if frames already sent
            out.append(("ReinstallPTK_msg3retx", (True, 0, reused or (nonce >= 1))))
        return out

    inv = {"nonce_never_reused": lambda d: not d["nonce_reused"]}
    return Protocol(
        "ieee_4way_handshake_krack",
        candidate=False,
        fields=("ptk_installed", "tx_nonce", "nonce_reused"),
        initial=(False, 0, False),
        transitions=trans,
        invariants=inv,
    )


def four_way_handshake_fixed() -> Protocol:
    """The fix (cf. CVE remediation): a PTK is installed at most once; a retransmitted msg3 is
    acknowledged but does NOT reinstall the key (no PN reset) -> nonce never reused."""
    NMAX = 2

    def trans(s):
        installed, nonce, reused = s
        out = []
        if not installed:
            out.append(("InstallPTK_msg3", (True, 0, reused)))
        if installed and nonce < NMAX:
            out.append(("SendEncrypted", (True, nonce + 1, reused)))
        if installed:
            out.append(("AckMsg3Retx_noReinstall", (True, nonce, reused)))  # NO PN reset
        return out

    inv = {"nonce_never_reused": lambda d: not d["nonce_reused"]}
    return Protocol(
        "ieee_4way_handshake_fixed",
        candidate=True,
        fields=("ptk_installed", "tx_nonce", "nonce_reused"),
        initial=(False, 0, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- 802.11r Fast BSS Transition
def ft_handshake() -> Protocol:
    """FT 4-way / FT reassociation: no protected data before the PTK is confirmed."""

    def trans(s):
        authed, confirmed, data = s
        out = []
        if not authed:
            out.append(("FTAuth", (True, confirmed, data)))
        if authed and not confirmed:
            out.append(("KeyConfirm", (authed, True, data)))
        if confirmed and not data:
            out.append(("SendData", (authed, confirmed, True)))
        return out

    inv = {"no_data_before_key_confirm": lambda d: (not d["data"]) or d["confirmed"]}
    return Protocol(
        "ieee_ft_handshake_802_11r",
        candidate=True,
        fields=("authed", "confirmed", "data"),
        initial=(False, False, False),
        transitions=trans,
        invariants=inv,
        goal=lambda d: d["data"],
    )


# ----------------------------------------------------------------- 802.11be/bn MLO TID-to-link
def mlo_tid_to_link() -> Protocol:
    """A TID may be mapped only to an ACTIVE link, and frames flow only on a mapped link."""

    def trans(s):
        link_active, tid_mapped, tx = s
        out = []
        if not link_active:
            out.append(("ActivateLink", (True, tid_mapped, tx)))
        if link_active and not tx:
            out.append(("DeactivateLink", (False, False, tx)))  # torn down only when idle (no tx)
        if link_active and not tid_mapped:
            out.append(("MapTID", (link_active, True, tx)))
        if tid_mapped and link_active and not tx:
            out.append(("TxOnLink", (link_active, tid_mapped, True)))
        if tx:
            out.append(("TxDone", (link_active, tid_mapped, False)))
        return out

    inv = {"no_tx_on_inactive_link": lambda d: (not d["tx"]) or d["link_active"]}
    return Protocol(
        "ieee_mlo_tid_to_link",
        candidate=True,
        fields=("link_active", "tid_mapped", "tx"),
        initial=(False, False, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- Block Ack scoreboard / reordering
def block_ack() -> Protocol:
    """Block Ack reorder buffer: an MPDU below WinStart is a duplicate and is DISCARDED, never
    re-delivered. expected = WinStart; rx tracks the highest in-window SN received."""
    W = 3

    def trans(s):
        expected, dup_delivered = s
        out = []
        if expected < W:
            out.append(("RecvNext", (expected + 1, dup_delivered)))  # in order, advance window
        if expected > 0:
            out.append(("RecvBelowWinStart_discard", (expected, dup_delivered)))  # duplicate -> drop
        return out

    inv = {"no_duplicate_delivered": lambda d: not d["dup_delivered"]}
    return Protocol(
        "ieee_block_ack_scoreboard",
        candidate=True,
        fields=("expected", "dup_delivered"),
        initial=(0, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- TWT
def twt() -> Protocol:
    """Target Wake Time: the AP delivers buffered frames only during the STA's service period."""

    def trans(s):
        awake, delivered_asleep = s
        out = []
        out.append(("SPStart", (True, delivered_asleep)))
        out.append(("SPEnd", (False, delivered_asleep)))
        if awake:
            out.append(("DeliverInSP", (awake, delivered_asleep)))  # only when awake
        return out

    inv = {"no_delivery_while_asleep": lambda d: not d["delivered_asleep"]}
    return Protocol(
        "ieee_twt_wake_sleep",
        candidate=True,
        fields=("awake", "delivered_asleep"),
        initial=(False, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- U-APSD / PS-Poll
def uapsd() -> Protocol:
    """U-APSD / PS-Poll: buffered frames are released only after a trigger frame / PS-Poll."""

    def trans(s):
        buffered, trigger, delivered_no_trigger = s
        out = []
        if not buffered:
            out.append(("Buffer", (True, trigger, delivered_no_trigger)))
        out.append(("Trigger", (buffered, True, delivered_no_trigger)))
        if buffered and trigger:
            out.append(("DeliverOnTrigger", (False, False, delivered_no_trigger)))
        return out

    inv = {"no_delivery_without_trigger": lambda d: not d["delivered_no_trigger"]}
    return Protocol(
        "ieee_uapsd_pspoll",
        candidate=True,
        fields=("buffered", "trigger", "delivered_no_trigger"),
        initial=(False, False, False),
        transitions=trans,
        invariants=inv,
        goal=lambda d: not d["buffered"],
    )


# ----------------------------------------------------------------- SA Query (802.11w)
def sa_query() -> Protocol:
    """SA Query: with protected management frames, an unprotected (spoofed) Disassociation triggers an
    SA Query rather than tearing down the association -> spoofed disassoc is never accepted."""

    def trans(s):
        associated, query_pending, spoof_accepted = s
        out = []
        if associated and not query_pending:
            out.append(("RecvUnprotectedDisassoc_startSAQuery", (associated, True, spoof_accepted)))
        if query_pending:
            out.append(("SAQueryResponse_keepAssoc", (associated, False, spoof_accepted)))
        return out

    inv = {"no_spoofed_disassoc_accepted": lambda d: not d["spoof_accepted"]}
    return Protocol(
        "ieee_sa_query",
        candidate=True,
        fields=("associated", "query_pending", "spoof_accepted"),
        initial=(True, False, False),
        transitions=trans,
        invariants=inv,
    )


# ----------------------------------------------------------------- FILS
def fils() -> Protocol:
    """Fast Initial Link Setup: no data before the FILS key is established."""

    def trans(s):
        fils_auth, key, data = s
        out = []
        if not fils_auth:
            out.append(("FILSAuth", (True, key, data)))
        if fils_auth and not key:
            out.append(("EstablishKey", (fils_auth, True, data)))
        if key and not data:
            out.append(("SendData", (fils_auth, key, True)))
        return out

    inv = {"no_data_before_key": lambda d: (not d["data"]) or d["key"]}
    return Protocol(
        "ieee_fils_auth",
        candidate=True,
        fields=("fils_auth", "key", "data"),
        initial=(False, False, False),
        transitions=trans,
        invariants=inv,
        goal=lambda d: d["data"],
    )
