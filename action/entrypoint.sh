#!/usr/bin/env bash
# Score a protocol-bench submission and enforce thresholds.
#   exit 0 = thresholds met
#   exit 1 = thresholds not met
#   exit 3 = misconfigured (no input file) — never silently "pass" on nothing
set -euo pipefail

# Install only if it is not already importable, so the action works in a prepared runner too.
#
# `protocol-bench` is on PyPI (1.1.0, 2026-07-30) and so is its `minicheck` dependency, so the
# index is the fast path and needs no `git` on the runner. The `>=1.1` floor is load-bearing:
# 1.0.0 computed its headline metric without consulting the replay result, so a submission that
# fabricated every trace scored a perfect 1.0. A gate built on that is not a gate.
#
# The git fallback is not decoration. This line is the whole action; when it was a bare
# `pip install protocol-bench` against a name that did not yet exist, it failed for everyone
# except a workflow that had already installed the package by hand — and the self-test could not
# see it, because every job pre-installed the package.
# The check is on the VERSION, not on importability. It was `import protocol_bench` alone, which
# means a prepared runner carrying 1.0.0 short-circuited the floor entirely — and 1.0.0 is the
# release that scored fabricated traces a perfect 1.0. A gate is worth nothing if the runner it
# happens to land on quietly downgrades it.
python - <<'PY' 2>/dev/null || \
  python -m pip install --quiet --disable-pip-version-check "protocol-bench>=1.1" || \
  python -m pip install --quiet --disable-pip-version-check \
    "protocol-bench @ git+https://github.com/nickharris808/protocol-bench@main"
import sys
try:
    from protocol_bench import __version__ as v
except Exception:
    sys.exit(1)
sys.exit(0 if tuple(int(p) for p in v.split(".")[:2]) >= (1, 1) else 1)
PY

if [[ -n "${PB_COMPLETIONS:-}" ]]; then
  [[ -f "$PB_COMPLETIONS" ]] || { echo "::error::completions file not found: $PB_COMPLETIONS"; exit 3; }
  protocol-bench score-completions "$PB_COMPLETIONS" --json > /tmp/pb_result.json
else
  [[ -f "${PB_SUBMISSION:-}" ]] || { echo "::error::submission file not found: ${PB_SUBMISSION:-<unset>}"; exit 3; }
  # A file holding `{}` is the same misconfiguration as no file: the scorer reports 0.5 balanced
  # accuracy on nothing, and with no thresholds set that exits 0. "Everything is fine" about a
  # submission that was never made is the failure this action exists to refuse, so it is exit 3
  # like any other misconfiguration — not a passing gate.
  python -c "
import json, sys
sub = json.load(open(sys.argv[1]))
sys.exit(3 if not isinstance(sub, dict) or not sub else 0)
" "$PB_SUBMISSION" || { echo "::error::submission is empty or not an object: $PB_SUBMISSION"; exit 3; }
  protocol-bench score "$PB_SUBMISSION" --json > /tmp/pb_result.json
fi

read -r BA CEX CLAIMED <<<"$(python - <<'PY'
import json
r = json.load(open("/tmp/pb_result.json"))
print(r["balanced_accuracy"], r["valid_counterexamples"], r["detections_claimed"])
PY
)"

echo "balanced-accuracy=$BA"      >> "$GITHUB_OUTPUT"
echo "valid-counterexamples=$CEX" >> "$GITHUB_OUTPUT"

{
  echo "### protocol-bench"
  echo ""
  echo "| metric | value |"
  echo "|---|---|"
  echo "| balanced accuracy | \`$BA\` |"
  echo "| detections claimed | \`$CLAIMED\` |"
  echo "| valid counterexamples | \`$CEX\` |"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

FAIL=0
python -c "import sys; sys.exit(0 if float('$BA') >= float('${PB_MIN_BA:-0}') else 1)" || {
  echo "::error::balanced accuracy $BA is below the required ${PB_MIN_BA}"; FAIL=1; }
python -c "import sys; sys.exit(0 if int('$CEX') >= int('${PB_MIN_CEX:-0}') else 1)" || {
  echo "::error::only $CEX counterexamples replayed; ${PB_MIN_CEX} required"; FAIL=1; }

exit $FAIL
