"""E17-T02 part B: nightly mutation fuzz of the CVWB decoder (SR-155) seeded from the corpus.

Excluded from the PR lane (``-m "not fuzz"``); default 200 examples, nightly sets
``CV_FUZZ_EXAMPLES=20000``.
Invariant: ``decode`` returns a ``Frame`` or raises ONLY ``FrameMalformedError``, and one decode
never allocates more than ``MAX_PEAK_BYTES`` (SR-128: wire counts never size an allocation).
Failing inputs are written to ``CV_FUZZ_ARTIFACT_DIR`` (uploaded as a CI artefact, never the repo).
"""

from __future__ import annotations

import json
import os
import struct
import tracemalloc
from pathlib import Path
from typing import Final

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.ws.binary import FrameMalformedError, decode

REPO = Path(__file__).resolve().parents[5]
SEEDS: Final[list[bytes]] = [
    bytes.fromhex(s["hex"])
    for s in json.loads((REPO / "tests/fuzz/ws-frames/corpus.json").read_text(encoding="utf-8"))
]
EXAMPLES: Final[int] = int(os.environ.get("CV_FUZZ_EXAMPLES", "200"))
MAX_PEAK_BYTES: Final[int] = 1 << 20
_INTERESTING: Final[tuple[int, ...]] = (0, 1, 2, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFFE)

_op = st.one_of(
    st.tuples(st.just("flip"), st.integers(0, 400), st.integers(0, 7)),
    st.tuples(st.just("trunc"), st.integers(0, 400), st.just(0)),
    st.tuples(st.just("count"), st.integers(0, 400), st.sampled_from(_INTERESTING)),
    st.tuples(st.just("extend"), st.integers(0, 64), st.integers(0, 255)),
    st.tuples(st.just("set"), st.integers(0, 400), st.integers(0, 255)),
)


def mutate(seed: bytes, ops: list[tuple[str, int, int]]) -> bytes:
    buf = bytearray(seed)
    for kind, a, b in ops:
        if kind == "trunc":
            del buf[a:]
        elif kind == "extend":
            buf.extend(bytes([b]) * a)
        elif not buf:
            continue
        elif kind == "flip":
            buf[a % len(buf)] ^= 1 << b
        elif kind == "set":
            buf[a % len(buf)] = b
        elif len(buf) >= 4:  # count tampering: rewrite a u32 at any offset
            struct.pack_into("<I", buf, a % (len(buf) - 3), b)
    return bytes(buf)


def _save_failure(data: bytes) -> None:
    out = os.environ.get("CV_FUZZ_ARTIFACT_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / f"cvwb-fail-{abs(hash(data)):x}.bin").write_bytes(data)


@pytest.mark.fuzz
@settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
)
@given(i=st.integers(0, len(SEEDS) - 1), ops=st.lists(_op, min_size=1, max_size=6))
def test_decode_mutated_corpus_raises_only_the_typed_error(
    i: int, ops: list[tuple[str, int, int]]
) -> None:
    data = mutate(SEEDS[i], ops)
    tracemalloc.start()
    try:
        try:
            decode(data)
        except FrameMalformedError:
            pass
        except BaseException:
            _save_failure(data)
            raise
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if peak > MAX_PEAK_BYTES:
        _save_failure(data)
    assert peak <= MAX_PEAK_BYTES, f"decode peaked at {peak} B on {data.hex()}"
