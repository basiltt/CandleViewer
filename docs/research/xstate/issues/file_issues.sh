#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# file_issues.sh -- create the CandleViewer evaluation issues on GitHub
# -----------------------------------------------------------------------------
#
#   >>> DO NOT RUN THIS WITHOUT THE REPO OWNER'S EXPLICIT GO-AHEAD. <<<
#
# This script creates 17 labels and 35 issues (1 meta + 34 defects) on a GitHub
# repository. It is generated from the YAML front-matter of the issue files in
# this directory and is committed as a reviewable artefact, not as a step in any
# automated pipeline. Nothing here has been executed.
#
# Review first:
#   ./file_issues.sh --dry-run          # print every gh command, run nothing
#
# Then, only with the owner's approval:
#   ./file_issues.sh --repo basiltt/xstate-statemachine
#
# Behaviour
# ---------
# * Labels are created first (idempotent -- an existing label is left alone).
# * Issues are created in DEPENDENCY ORDER: the meta-issue first so it can be
#   referenced, then the root-cause defects that other issues build on, then
#   the rest. The order matches the upstream priority list in
#   00-META-candleviewer-adoption-readiness.md section 5.
# * Each issue body is the issue file with its YAML front-matter stripped, plus
#   a footer linking back to the meta-issue and naming the repro script.
# * Created issue numbers are appended to ./.filed-issues so a re-run can be
#   checked against them. The script refuses to run if that file already exists,
#   to prevent accidental duplicate filing.
#
# Requirements: gh (authenticated), python3/python/py (front-matter stripping).
# -----------------------------------------------------------------------------

set -euo pipefail

REPO=""
DRY_RUN=0
LEDGER="$(dirname "$0")/.filed-issues"

usage() {
  cat <<'EOF'
Usage: ./file_issues.sh [--repo OWNER/NAME] [--dry-run]

  --repo OWNER/NAME   target repository (default: basiltt/xstate-statemachine)
  --dry-run           print the gh commands without executing any of them
  -h, --help          this message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)    REPO="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

REPO="${REPO:-basiltt/xstate-statemachine}"
cd "$(dirname "$0")"

# -----------------------------------------------------------------------------
# Safety rails
# -----------------------------------------------------------------------------
if [[ $DRY_RUN -eq 0 ]]; then
  if [[ -f "$LEDGER" ]]; then
    echo "REFUSING TO RUN: $LEDGER exists -- issues appear to have been filed already." >&2
    echo "Delete it deliberately if you really intend to file again." >&2
    exit 1
  fi
  command -v gh >/dev/null || { echo "gh not found on PATH" >&2; exit 1; }
  gh auth status >/dev/null 2>&1 || { echo "gh is not authenticated" >&2; exit 1; }

  echo "About to create 17 labels and 35 issues on: $REPO"
  echo "This is NOT reversible in bulk."
  read -r -p "Type the repo name to confirm: " confirm
  [[ "$confirm" == "$REPO" ]] || { echo "Confirmation did not match. Aborted." >&2; exit 1; }
fi

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '%q ' "$@"; printf '\n'
  else
    "$@"
  fi
}

# -----------------------------------------------------------------------------
# 1. Labels
# -----------------------------------------------------------------------------
echo "=== creating labels ==="

mklabel() {  # name, colour, description
  if [[ $DRY_RUN -eq 1 ]]; then
    printf 'gh label create %q --repo %q --color %q --description %q --force\n' "$1" "$REPO" "$2" "$3"
  else
    gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force \
      || echo "  (label '$1' already exists or could not be created -- continuing)"
  fi
}

# type
mklabel bug                    d73a4a "Something is not working as documented or as XState v5 specifies"
mklabel enhancement            a2eeef "A missing capability"
mklabel documentation          0075ca "Documentation gap or inaccuracy"
mklabel performance            fbca04 "Throughput, latency, memory or timing"
mklabel meta                   ededed "Umbrella / tracking issue"
mklabel tracking               ededed "Tracks a set of other issues"

# severity (relative to a production trading system, per the register's scale)
mklabel severity/blocker       b60205 "Can cause financial loss or silent data corruption on the order path"
mklabel severity/high          d93f0b "Silent wrongness, or a hard architectural constraint"
mklabel severity/medium        fbca04 "Surprising or costly; worked around at moderate expense"
mklabel severity/low           0e8a16 "Ergonomics, waste or maintainability"

# area
mklabel area/interpreter       1d76db "base_interpreter / interpreter core algorithm"
mklabel area/sync-interpreter  1d76db "SyncInterpreter engine"
mklabel area/actors            1d76db "invoke, spawn, sendTo, actor registry"
mklabel area/persistence       1d76db "Snapshot, restore, from_snapshot"
mklabel area/timers            1d76db "after transitions, clocks, scheduling"
mklabel area/validation        1d76db "create_machine validation and strictness"
mklabel area/perf              1d76db "Hot path cost and scaling"
mklabel area/docs              1d76db "Docs site and reference material"

# provenance
mklabel candleviewer           5319e7 "Found during the CandleViewer trading-terminal evaluation of 0.7.0"

# -----------------------------------------------------------------------------
# 2. Issues, in dependency order
# -----------------------------------------------------------------------------
#
# Order rationale (see meta-issue section 5):
#   meta first        -- so every later issue can reference it
#   LC-01, LC-03      -- the two root causes that retire the most downstream work
#   LC-02             -- shares a root cause (base_interpreter.py:1769) with LC-04
#   LC-08, LC-07, LC-36 -- the validation cluster; cheap, self-contained
#   LC-48             -- observability; makes the above visible even unfixed
#   LC-06, LC-09, LC-05 -- remaining semantics
#   LC-43, LC-41, LC-42 -- flow control group
#   LC-16, LC-12, LC-29, LC-28 -- actors group
#   LC-19..LC-24      -- persistence group
#   LC-26, LC-27, LC-38 -- timing/threading group
#   LC-34, LC-37      -- validation/typing
#   LC-39, LC-44, LC-45, LC-53 -- perf + docs of measured behaviour
#   LC-32, LC-49, LC-47, LC-57 -- cleanup, umbrella last
#
ORDER=(
  00-META-candleviewer-adoption-readiness.md
  LC-01-action-raise-commits-transition.md
  LC-03-unhandled-events-discarded.md
  LC-02-always-self-target-deadlock.md
  LC-08-unknown-target-unvalidated.md
  LC-07-relative-dot-target-silent-noop.md
  LC-36-builtin-action-params-misspelled.md
  LC-48-no-error-observability-hooks.md
  LC-06-overforgiving-target-resolution.md
  LC-09-guard-exception-swallowed.md
  LC-05-raise-not-macrostep.md
  LC-43-cross-thread-send-silently-lost.md
  LC-41-unbounded-queue-no-backpressure.md
  LC-42-send-fire-and-forget-no-answer.md
  LC-16-sendto-invoke-id.md
  LC-12-spawn-blocking-async-engine.md
  LC-29-invoke-input-static-ignored.md
  LC-28-actor-poll-two-tasks.md
  LC-19-restore-does-not-restart-invokes.md
  LC-21-no-snapshot-schema-version.md
  LC-22-from-snapshot-context-wholesale.md
  LC-24-pending-queue-lost-on-crash.md
  LC-26-after-timer-starvation.md
  LC-27-no-clock-injection.md
  LC-38-sync-interpreter-timer-threads.md
  LC-34-no-strict-mode.md
  LC-37-arity-misclassification.md
  LC-39-throughput-global-budget.md
  LC-44-pure-api-slower-and-skips-actions.md
  LC-45-hot-path-alloc-and-info-logging.md
  LC-53-undocumented-production-characteristics.md
  LC-32-terminal-machines-not-reaped.md
  LC-49-no-hierarchical-state-value.md
  LC-47-target-str-mutation-shared-definition.md
  LC-57-two-engines-duplicate-core-algorithm.md
)

# Front-matter parser: prints "title", "labels" (comma-joined) or the body.
# Resolve a Python interpreter once (python3 is absent on stock Windows).
PYBIN=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys" >/dev/null 2>&1; then
    PYBIN="$cand"; break
  fi
done
[[ -n "$PYBIN" ]] || { echo "no usable python interpreter found on PATH" >&2; exit 1; }

read_fm() {  # file, field
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PYBIN" - "$1" "$2" <<'PY'
import re, sys
path, field = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
fm, body = (m.group(1), m.group(2)) if m else ("", text)
if field == "body":
    sys.stdout.write(body.lstrip("\n"))
elif field == "labels":
    lm = re.search(r"^labels:\s*\[(.*?)\]\s*$", fm, re.M)
    print(",".join(s.strip() for s in lm.group(1).split(",")) if lm else "")
else:
    fmm = re.search(rf'^{field}:\s*"?(.*?)"?\s*$', fm, re.M)
    print(fmm.group(1) if fmm else "")
PY
}

echo
echo "=== creating issues (${#ORDER[@]} total) ==="

META_REF=""
for file in "${ORDER[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "MISSING: $file -- skipping" >&2
    continue
  fi

  title="$(read_fm "$file" title)"
  labels="$(read_fm "$file" labels)"
  lc="$(read_fm "$file" lc)"
  repro="$(read_fm "$file" repro_script)"

  body_file="$(mktemp)"
  read_fm "$file" body > "$body_file"

  # Footer: provenance, repro, and a back-link to the meta-issue.
  {
    printf '\n\n---\n\n'
    printf '### Provenance\n\n'
    printf 'Found during the **CandleViewer** trading-terminal evaluation of '
    printf '`xstate-statemachine` **0.7.0** (commit `42612cf`) on Python 3.13.7.\n\n'
    if [[ -n "$repro" ]]; then
      printf 'Self-contained repro: `%s` — exits **1** while the defect is present, ' "$repro"
      printf '**0** once it is fixed, so it can be adopted directly as a regression test.\n\n'
    fi
    if [[ -n "$META_REF" && "$lc" != "LC-00-META" ]]; then
      printf 'Part of the tracking issue %s.\n' "$META_REF"
    fi
    printf '\nHappy to open a PR for this one — see the contribution offer in the tracking issue.\n'
  } >> "$body_file"

  echo "--- $lc  $title"

  if [[ $DRY_RUN -eq 1 ]]; then
    printf 'gh issue create --repo %q --title %q --label %q --body-file %q\n' \
      "$REPO" "$title" "$labels" "$file"
    rm -f "$body_file"
    continue
  fi

  url="$(gh issue create --repo "$REPO" \
          --title "$title" \
          --label "$labels" \
          --body-file "$body_file")"

  echo "    -> $url"
  printf '%s\t%s\t%s\n' "$lc" "$file" "$url" >> "$LEDGER"

  # The first created issue is the meta-issue; later issues link back to it.
  if [[ -z "$META_REF" ]]; then
    META_REF="$url"
  fi

  rm -f "$body_file"
  sleep 2   # be polite to the API; avoids secondary rate limits
done

echo
if [[ $DRY_RUN -eq 1 ]]; then
  echo "Dry run complete. Nothing was created."
else
  echo "Done. Created issues are recorded in $LEDGER"
  echo
  echo "Follow-up, by hand:"
  echo "  1. Edit the meta-issue checklist to use the real issue numbers."
  echo "  2. Offer the repro corpus as a PR (tests/regression/candleviewer/)."
fi
