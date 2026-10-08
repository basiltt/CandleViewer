"""E17-T02: CVWB codec — hypothesis round trip, malformed cases, SR-128, drift + SR-155 corpus."""

from __future__ import annotations

import json
import struct
import tracemalloc
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.ws import cvwb_vectors
from candleviewer.ws._generated import cvwb_layout
from candleviewer.ws.binary import (
    BARS,
    BOOK_DELTA,
    BOOK_SNAPSHOT,
    FOOTPRINT,
    HEATMAP_COLUMN,
    TRADES,
    Frame,
    FrameEncodeError,
    FrameMalformedError,
    decode,
    decode_b64,
    encode,
    encode_b64,
)

REPO = Path(__file__).resolve().parents[5]
U8 = st.integers(0, 2**8 - 1)
U32 = st.integers(0, 2**32 - 1)
U64 = st.integers(0, 2**64 - 1)
I64 = st.integers(-(2**63), 2**63 - 1)
SIDE = st.sampled_from((0, 1))

_RECORD = {
    BOOK_SNAPSHOT: st.tuples(SIDE, I64, U64),
    BOOK_DELTA: st.tuples(SIDE, I64, U64),
    TRADES: st.tuples(U32, I64, U64, SIDE, U8),
    BARS: st.tuples(U64, U64, U32, I64, I64, I64, I64, U64, U64, U32, I64, U8),
    FOOTPRINT: st.tuples(I64, U64, U64, U32, U8),
    HEATMAP_COLUMN: st.tuples(U64, U64),
}


@st.composite
def frames(draw: st.DrawFn) -> Frame:
    kind = draw(st.sampled_from(sorted(_RECORD)))
    rec = _RECORD[kind]
    flags = draw(st.integers(0, 0b1111))
    ps = draw(st.integers(0, 8))
    qs = draw(st.integers(0, 8))
    ts = draw(U64)
    if kind == FOOTPRINT:
        groups = draw(st.lists(st.tuples(U32, st.lists(rec, max_size=6).map(tuple)), max_size=6))
        return Frame(kind, (), flags, ps, qs, ts, groups=tuple(groups))
    records = tuple(draw(st.lists(rec, max_size=6)))
    if kind == BOOK_SNAPSHOT:
        return Frame(kind, records, flags, ps, qs, ts, trailer=draw(st.tuples(U64, U64)))
    if kind == HEATMAP_COLUMN:
        return Frame(kind, records, flags, ps, qs, ts, prefix=draw(st.tuples(U32, I64, I64)))
    return Frame(kind, records, flags, ps, qs, ts)


@settings(max_examples=300, deadline=None)
@given(frames())
def test_codec_round_trip_any_valid_frame_is_exact(frame: Frame) -> None:
    raw = encode(frame)
    assert decode(raw) == frame
    assert encode(decode(raw)) == raw  # byte-identical re-encode (ADR-0005)
    assert decode_b64(encode_b64(frame)) == frame


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=200))
def test_decode_arbitrary_bytes_never_raises_anything_else(data: bytes) -> None:
    try:
        decode(data)
    except FrameMalformedError:
        pass


@given(frames(), st.binary(min_size=1, max_size=16))
def test_decode_trailing_bytes_follow_the_per_kind_rule(frame: Frame, extra: bytes) -> None:
    raw = encode(frame) + extra
    if frame.body_kind == BARS:
        with pytest.raises(FrameMalformedError):
            decode(raw)
    else:
        assert decode(raw) == frame


def _hdr(kind: int, count: int, ver: int = 1, magic: int = 0x43565742) -> bytes:
    return struct.pack("<IBBBBB3xIQ", magic, ver, kind, 0, 2, 3, count, 0)


@pytest.mark.parametrize(
    ("data", "diagnostic"),
    [
        (b"", "frame_malformed"),
        (_hdr(BOOK_DELTA, 0, magic=0)[:20], "frame_malformed"),
        (_hdr(BOOK_DELTA, 0, magic=0x42575643), "frame_malformed"),
        (_hdr(BOOK_DELTA, 0, ver=2), "unsupported_format_version"),
        (_hdr(BARS, 0, ver=1), "unsupported_format_version"),
        (_hdr(9, 0), "unsupported_body_kind"),
        (_hdr(TRADES, 2) + bytes(43), "frame_malformed"),
        (_hdr(BOOK_SNAPSHOT, 0) + bytes(15), "frame_malformed"),
        (_hdr(HEATMAP_COLUMN, 1) + bytes(10), "frame_malformed"),
        (_hdr(FOOTPRINT, 1) + bytes(4), "frame_malformed"),
    ],
    ids=[
        "empty",
        "short-header",
        "magic",
        "version",
        "bars-v1",
        "kind",
        "short",
        "trailer",
        "hm-prefix",
        "fp-prefix",
    ],
)
def test_decode_malformed_input_raises_typed_error(data: bytes, diagnostic: str) -> None:
    with pytest.raises(FrameMalformedError) as info:
        decode(data)
    assert info.value.diagnostic == diagnostic
    assert info.value.code == "frame_malformed"


def test_decode_max_u32_count_rejects_without_proportional_allocation() -> None:
    """SR-128 / Gherkin: record_count=2^32-1, 32-byte body -> reject, no big allocation."""
    data = _hdr(BOOK_DELTA, 2**32 - 1) + bytes(32)
    tracemalloc.start()
    try:
        with pytest.raises(FrameMalformedError):
            decode(data)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 64 * 1024


def test_decode_b64_rejects_non_base64() -> None:
    with pytest.raises(FrameMalformedError):
        decode_b64("not*base64")


@pytest.mark.parametrize(
    "frame",
    [
        Frame(9),
        Frame(BOOK_DELTA, flags=0b1_0000),
        Frame(BOOK_DELTA, ((2, 0, 0),)),
        Frame(BOOK_DELTA, ((0, 2**63, 0),)),
        Frame(BOOK_SNAPSHOT),
        Frame(BOOK_DELTA, trailer=(0, 0)),
        Frame(HEATMAP_COLUMN),
        Frame(FOOTPRINT),
        Frame(FOOTPRINT, ((1, 2, 3, 4, 5),), groups=()),
    ],
    ids=[
        "kind",
        "flags",
        "side",
        "range",
        "no-trailer",
        "extra-trailer",
        "no-prefix",
        "no-groups",
        "records-outside-groups",
    ],
)
def test_encode_unrepresentable_frame_raises(frame: Frame) -> None:
    with pytest.raises(FrameEncodeError):
        encode(frame)


def test_encode_header_derives_version_and_counts() -> None:
    raw = encode(Frame(HEATMAP_COLUMN, ((1, 2),), prefix=(0, 0, 1)))
    assert raw[4] == 1 and raw[5] == HEATMAP_COLUMN
    assert struct.unpack_from("<I", raw, 12)[0] == 1
    assert encode(Frame(BARS))[4] == 2


# --- drift: one declaration drives both implementations ---------------------------------

_SIZES = {"u8": 1, "u32": 4, "u64": 8, "i64": 8, "pad3": 3, "pad4": 4}


def test_generated_python_layout_matches_the_declaration() -> None:
    doc = json.loads((REPO / "packages/protocol/cvwb-layout.json").read_text(encoding="utf-8"))
    assert cvwb_layout.MAGIC == doc["magic"] == 0x43565742
    assert struct.calcsize(cvwb_layout.HEADER.fmt) == doc["header_bytes"] == 24
    for k in doc["kinds"]:
        gen = cvwb_layout.KINDS[k["id"]]
        assert (gen.name, gen.format_version, gen.length_rule) == (
            k["name"],
            k["format_version"],
            k["length_rule"],
        )
        assert gen.record.size == k["record_bytes"] == struct.calcsize(gen.record.fmt)
        assert gen.record.size == sum(_SIZES[f["type"]] for f in k["record"])


@pytest.mark.parametrize("name", ["vectors.json", "corpus.json"])
def test_committed_vectors_and_corpus_are_fresh(name: str) -> None:
    path, render = {
        "vectors.json": (
            REPO / "packages/fixtures/golden/cvwb/vectors.json",
            cvwb_vectors.render_vectors,
        ),
        "corpus.json": (REPO / "tests/fuzz/ws-frames/corpus.json", cvwb_vectors.render_corpus),
    }[name]
    assert path.read_text(encoding="utf-8") == render(), "run scripts/generate_cvwb_vectors.py"


def test_fuzz_corpus_every_seed_behaves_as_declared() -> None:
    """SR-155: each committed seed is accepted or rejected exactly as declared, never crashes."""
    seeds = json.loads((REPO / "tests/fuzz/ws-frames/corpus.json").read_text(encoding="utf-8"))
    assert len(seeds) >= 40
    for seed in seeds:
        try:
            decode(bytes.fromhex(seed["hex"]))
            got = "ok"
        except FrameMalformedError:
            got = "malformed"
        assert got == seed["expect"], seed["name"]
