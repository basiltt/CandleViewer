"""F1 -- machine-definition fuzzer.

Contract under test (from the library's own docs / CHANGELOG):

  A1. ``create_machine`` on a structurally VALID config must succeed.
  A2. ``create_machine`` on an INVALID config must raise one of
      ``ALLOWED_BUILD_ERRORS`` -- never a bare Python error
      (``TypeError``/``AttributeError``/``KeyError``/``RecursionError``/
      ``ValueError``), and never hang.
  A3. Build-time target validation (#29/#30) is a shipped guarantee: a
      config with a target that cannot resolve must NOT build silently
      under the default ``strict_targets=True``.
  A4. A successfully built machine must be startable (both engines) --
      a config that builds but explodes on ``start()`` with a non-library
      error is a build-validation gap.

Usage:
    python f1_machine_config.py [--cases N] [--seed S]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import HealthCheck, Phase, given, settings, seed as hseed
from hypothesis import strategies as st

from common import (  # noqa: E402
    ALLOWED_BUILD_ERRORS,
    OUT,
    Recorder,
    exc_sig,
)

# 🛟 The budgeted `_select_transitions` patch MUST be installed before any
#    interpreter runs: without it a single non-settling config (D-fuzz-1)
#    wedges the whole fuzz run and consumes memory without bound.
from spin_oracle import Spin  # noqa: E402,F401  (import installs the patch)
import spin_oracle  # noqa: E402

SPIN_LIMIT = 20000
spin_oracle._STATE["limit"] = SPIN_LIMIT
from gen_config import (  # noqa: E402
    MUTATIONS,
    apply_mutation,
    make_logic,
    valid_machine,
)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore")

REC = Recorder("F1 machine-definition fuzzer")


def _size(cfg: dict) -> int:
    return len(json.dumps(cfg, default=str))


def _build(cfg: dict, sync: bool):
    return create_machine(cfg, logic=make_logic(sync=sync))


# -----------------------------------------------------------------------------
# A1 / A4 -- valid configs build and start
# -----------------------------------------------------------------------------
def check_valid(cfg: dict) -> None:
    REC.cases += 1
    try:
        machine = _build(cfg, sync=True)
    except ALLOWED_BUILD_ERRORS as exc:
        # A typed rejection of a config we believe is valid: report it, but
        # separately from a crash -- it may be a generator bug, so the
        # message is kept for triage.
        REC.bump("valid.rejected_typed")
        REC.record(
            "A1-valid-config-rejected",
            exc_sig(exc),
            f"{type(exc).__name__}: {exc}",
            cfg,
            _size(cfg),
            exc,
        )
        return
    except BaseException as exc:  # noqa: BLE001
        REC.bump("valid.crash")
        REC.record(
            "A2-untyped-build-error",
            exc_sig(exc),
            f"valid config -> {type(exc).__name__}: {exc}",
            cfg,
            _size(cfg),
            exc,
        )
        return
    REC.bump("valid.built")

    # A4: it must be startable on the sync engine.
    try:
        spin_oracle._STATE["n"] = 0
        interp = SyncInterpreter(machine)
        interp.start()
        ids = interp.current_state_ids
        if not ids:
            REC.bump("valid.empty_configuration")
            REC.record(
                "A4-empty-configuration-after-start",
                "start-empty",
                "machine built and started but configuration is empty",
                cfg,
                _size(cfg),
            )
        interp.stop()
        REC.bump("valid.started_sync")
    except Spin as exc:
        REC.bump("valid.start_never_settles")
        REC.record(
            "A4-start-does-not-terminate",
            "transient-loop-unbounded",
            f"start() exceeded {SPIN_LIMIT} transition selections without "
            f"settling (non-terminating)",
            cfg,
            _size(cfg),
            exc,
        )
    except ALLOWED_BUILD_ERRORS as exc:
        REC.bump("valid.start_typed_error")
        REC.record(
            "A4-build-gap-typed-at-start",
            exc_sig(exc),
            f"built OK, start() -> {type(exc).__name__}: {exc}",
            cfg,
            _size(cfg),
            exc,
        )
    except BaseException as exc:  # noqa: BLE001
        REC.bump("valid.start_crash")
        REC.record(
            "A4-untyped-error-at-start",
            exc_sig(exc),
            f"built OK, start() -> {type(exc).__name__}: {exc}",
            cfg,
            _size(cfg),
            exc,
        )


# -----------------------------------------------------------------------------
# A2 / A3 -- mutated configs are rejected, with a typed error
# -----------------------------------------------------------------------------
# Mutations that are NOT guaranteed to be invalid: dropping an optional key
# or swapping in a value the library legitimately tolerates leaves a config
# that may still be sound. For those we only assert "no untyped crash".
ALWAYS_INVALID = {"dangle_target", "cycle_always", "dup_custom_id", "unknown_logic"}


def check_mutated(cfg: dict, kind: str, i: int, junk_i: int) -> None:
    REC.cases += 1
    mutated, desc = apply_mutation(cfg, kind, i, junk_i)
    repro = {"mutation": kind, "i": i, "junk_i": junk_i, "desc": desc, "config": mutated}
    try:
        machine = _build(mutated, sync=True)
    except ALLOWED_BUILD_ERRORS:
        REC.bump(f"mut.{kind}.typed_reject")
        return
    except RecursionError as exc:
        REC.bump(f"mut.{kind}.recursion")
        REC.record(
            "A2-recursion-error",
            f"{kind}",
            f"{desc} -> RecursionError (not a typed library error)",
            {"mutation": kind, "i": i, "junk_i": junk_i, "desc": desc},
            _size(cfg) + i,
            exc,
        )
        return
    except BaseException as exc:  # noqa: BLE001
        REC.bump(f"mut.{kind}.untyped")
        REC.record(
            "A2-untyped-build-error",
            f"{kind}/{exc_sig(exc)}",
            f"{desc} -> {type(exc).__name__}: {exc}",
            repro,
            _size(mutated),
            exc,
        )
        return

    REC.bump(f"mut.{kind}.accepted")
    if kind in ALWAYS_INVALID:
        REC.record(
            "A3-invalid-config-accepted",
            f"{kind}",
            f"{desc} -> create_machine() SUCCEEDED",
            repro,
            _size(mutated),
        )
        return
    # Accepted; make sure it at least does not crash untyped on start.
    try:
        spin_oracle._STATE["n"] = 0
        interp = SyncInterpreter(machine)
        interp.start()
        interp.stop()
    except Spin:
        REC.bump(f"mut.{kind}.start_never_settles")
        REC.record(
            "A4-start-does-not-terminate",
            f"transient-loop-unbounded/{kind}",
            f"{desc} -> start() never settles",
            repro,
            _size(mutated),
        )
    except ALLOWED_BUILD_ERRORS:
        REC.bump(f"mut.{kind}.start_typed")
    except BaseException as exc:  # noqa: BLE001
        REC.bump(f"mut.{kind}.start_untyped")
        REC.record(
            "A4-untyped-error-at-start",
            f"{kind}/{exc_sig(exc)}",
            f"{desc} -> built OK, start() {type(exc).__name__}: {exc}",
            repro,
            _size(mutated),
            exc,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260918)
    args = ap.parse_args()

    # 2/3 of the budget on mutated (defect-dense), 1/3 on valid.
    n_valid = args.cases // 3
    n_mut = args.cases - n_valid

    common_settings = dict(
        deadline=None,
        suppress_health_check=list(HealthCheck),
        phases=[Phase.generate],
        database=None,
    )

    @hseed(args.seed)
    @settings(max_examples=n_valid, **common_settings)
    @given(valid_machine())
    def run_valid(cfg):
        check_valid(cfg)

    @hseed(args.seed + 1)
    @settings(max_examples=n_mut, **common_settings)
    @given(
        valid_machine(),
        st.sampled_from(MUTATIONS),
        st.integers(min_value=0, max_value=40),
        st.integers(min_value=0, max_value=40),
    )
    def run_mut(cfg, kind, i, junk_i):
        check_mutated(cfg, kind, i, junk_i)

    run_valid()
    run_mut()

    REC.report()
    REC.dump(os.path.join(OUT, "f1_machine_config.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
