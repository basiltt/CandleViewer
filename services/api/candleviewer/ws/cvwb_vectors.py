"""Deterministic cross-language CVWB vectors and the SR-155 fuzz seed corpus (E17-T02).

Rendered by ``scripts/generate_cvwb_vectors.py`` into
``packages/fixtures/golden/cvwb/vectors.json`` (Python encode -> TS decode) and
``tests/fuzz/ws-frames/corpus.json`` (hostile seeds; both decoders must reject or accept
exactly as ``expect`` says, never crash). Both files are drift-checked by tests.
"""

from __future__ import annotations

import json
import struct

from candleviewer.ws.binary import (
    BARS,
    BOOK_DELTA,
    BOOK_SNAPSHOT,
    FOOTPRINT,
    HEATMAP_COLUMN,
    TRADES,
    Frame,
    encode,
)

_I64_MIN = -(2**63)
_U64_MAX = 2**64 - 1
_U32_MAX = 2**32 - 1


def vector_frames() -> list[tuple[str, Frame]]:
    """Named valid frames covering every kind, every flag bit, deletes and int extremes."""
    bar = (
        7,
        42,
        60_000,
        6_500_012,
        6_510_000,
        6_490_000,
        6_505_050,
        1_234_567,
        9 * 10**12,
        321,
        -4_567,
        1,
    )
    return [
        (
            "book_snapshot",
            Frame(
                BOOK_SNAPSHOT,
                ((0, 6_500_000, 1_500), (0, 6_499_950, 0), (1, 6_500_050, 2_000)),
                0b0001,
                2,
                3,
                1_789_132_262_104,
                trailer=(123_456, _U64_MAX),
            ),
        ),
        ("book_snapshot_empty", Frame(BOOK_SNAPSHOT, (), 0, 2, 3, 0, trailer=(0, 0))),
        (
            "book_delta_extremes",
            Frame(BOOK_DELTA, ((1, _I64_MIN, _U64_MAX), (0, 2**63 - 1, 0)), 0b1111, 8, 8, 2**63),
        ),
        (
            "trades",
            Frame(
                TRADES,
                ((0, 6_500_000, 10, 0, 0b001), (_U32_MAX, -1, 0, 1, 0b111)),
                0b0010,
                1,
                4,
                1_789_132_262_000,
            ),
        ),
        (
            "bars_v2",
            Frame(
                BARS,
                (bar, (7, 43, 120_000, 1, 2, 0, -1, 0, 0, 0, _I64_MIN, 0)),
                0b0100,
                2,
                3,
                1_789_132_200_000,
            ),
        ),
        ("bars_empty", Frame(BARS, (), 0, 0, 0, 0)),
        (
            "footprint",
            Frame(
                FOOTPRINT,
                (),
                0b1000,
                1,
                3,
                1_789_132_200_000,
                groups=(
                    (
                        0,
                        (
                            (6_500_000, 10, 20, 3, 0b1001),
                            (6_500_005, 0, _U64_MAX, _U32_MAX, 0b0110),
                        ),
                    ),
                    (60_000, ()),
                ),
            ),
        ),
        (
            "heatmap_column",
            Frame(
                HEATMAP_COLUMN,
                ((1, 2), (0, 0), (_U64_MAX, 7)),
                0,
                2,
                3,
                1_789_132_262_100,
                prefix=(100, 6_499_000, 5),
            ),
        ),
    ]


def render_vectors() -> str:
    out = []
    for name, f in vector_frames():
        out.append(
            {
                "name": name,
                "hex": encode(f).hex(),
                "body_kind": f.body_kind,
                "flags": f.flags,
                "price_scale": f.price_scale,
                "qty_scale": f.qty_scale,
                "ts_base_ms": str(f.ts_base_ms),
                "records": [[str(v) for v in r] for r in f.records],
                "trailer": None if f.trailer is None else [str(v) for v in f.trailer],
                "prefix": None if f.prefix is None else [str(v) for v in f.prefix],
                "groups": (
                    None
                    if f.groups is None
                    else [[str(ts), [[str(v) for v in c] for c in cells]] for ts, cells in f.groups]
                ),
            }
        )
    return json.dumps(out, indent=2) + "\n"


_HDR = struct.Struct("<IBBBBB3xIQ")
_MAGIC = 0x43565742


def _h(
    kind: int,
    count: int,
    *,
    ver: int | None = None,
    magic: int = _MAGIC,
    flags: int = 0,
    ps: int = 2,
    qs: int = 3,
    ts: int = 0,
) -> bytes:
    version = ver if ver is not None else (2 if kind == BARS else 1)
    return _HDR.pack(magic, version, kind, flags, ps, qs, count, ts)


def corpus_seeds() -> list[tuple[str, str, bytes]]:
    """``(name, expect, bytes)``; ``expect`` is ``ok`` or ``malformed`` (SR-155 seeds)."""
    one_bar = encode(vector_frames()[4][1])[24 : 24 + 85]
    book_rec = struct.pack("<BqQ", 0, 6_500_000, 1)
    nan_bits = struct.pack("<Q", 0x7FF8_0000_0000_0000)  # NaN-shaped bits in an int field
    s: list[tuple[str, str, bytes]] = [
        ("empty-buffer", "malformed", b""),
        ("header-truncated-23", "malformed", _h(BOOK_DELTA, 0)[:23]),
        ("bad-magic", "malformed", _h(BOOK_DELTA, 0, magic=0x42575643)),
        ("future-format-version", "malformed", _h(BOOK_DELTA, 0, ver=9)),
        ("unknown-body-kind-0", "malformed", _h(0, 0, ver=1)),
        ("unknown-body-kind-7", "malformed", _h(7, 0, ver=1)),
        ("zero-length-delta", "ok", _h(BOOK_DELTA, 0)),
        ("delta-count-max-u32-32b-body", "malformed", _h(BOOK_DELTA, _U32_MAX) + bytes(32)),
        ("delta-count-exceeds-buffer", "malformed", _h(BOOK_DELTA, 3) + book_rec * 2),
        ("delta-truncated-record", "malformed", _h(BOOK_DELTA, 1) + book_rec[:16]),
        ("delta-bad-side", "malformed", _h(BOOK_DELTA, 1) + b"\x02" + book_rec[1:]),
        ("delta-trailing-8-bytes", "ok", _h(BOOK_DELTA, 1) + book_rec + bytes(8)),
        ("scales-255", "ok", _h(BOOK_DELTA, 1, ps=255, qs=255) + book_rec),
        ("nan-shaped-size", "ok", _h(BOOK_DELTA, 1) + book_rec[:9] + nan_bits),
        ("all-flag-bits-set", "ok", _h(BOOK_DELTA, 0, flags=0xFF)),
        ("snapshot-missing-trailer", "malformed", _h(BOOK_SNAPSHOT, 1) + book_rec + bytes(15)),
        ("snapshot-count-max-u32", "malformed", _h(BOOK_SNAPSHOT, _U32_MAX) + bytes(16)),
        ("trades-count-max-u32", "malformed", _h(TRADES, _U32_MAX) + bytes(22)),
        ("trades-bad-side", "malformed", _h(TRADES, 1) + bytes(20) + b"\x07\x00"),
        # #2034 (bars v2, exact-length rule):
        ("bars-count-max-u32-one-record", "malformed", _h(BARS, _U32_MAX) + one_bar),
        ("bars-truncated-84", "malformed", _h(BARS, 1) + one_bar[:84]),
        ("bars-v1-header-85-body", "malformed", _h(BARS, 1, ver=1) + one_bar),
        ("bars-v2-header-69-body", "malformed", _h(BARS, 1) + one_bar[:69]),
        ("bars-count0-trailing", "malformed", _h(BARS, 0) + bytes(8)),
        ("bars-count1-trailing", "malformed", _h(BARS, 1) + one_bar + bytes(8)),
        ("bars-exact-one", "ok", _h(BARS, 1) + one_bar),
        ("footprint-groups-max-u32", "malformed", _h(FOOTPRINT, _U32_MAX) + bytes(8)),
        (
            "footprint-cell-count-oversized",
            "malformed",
            _h(FOOTPRINT, 1) + struct.pack("<II", 0, _U32_MAX) + bytes(33),
        ),
        ("footprint-group-prefix-truncated", "malformed", _h(FOOTPRINT, 2) + bytes(12)),
        ("footprint-empty-group", "ok", _h(FOOTPRINT, 1) + bytes(8)),
        ("heatmap-prefix-truncated", "malformed", _h(HEATMAP_COLUMN, 1) + bytes(23)),
        (
            "heatmap-row-count-max-u32",
            "malformed",
            _h(HEATMAP_COLUMN, 1) + struct.pack("<IqqI", 0, 0, 1, _U32_MAX) + bytes(16),
        ),
        (
            "heatmap-zero-rows-trailing",
            "ok",
            _h(HEATMAP_COLUMN, 1) + struct.pack("<IqqI", 0, 0, 1, 0) + bytes(5),
        ),
    ]
    s.extend((f"valid-{n}", "ok", encode(f)) for n, f in vector_frames())
    return s


def render_corpus() -> str:
    seeds = [{"name": n, "expect": e, "hex": b.hex()} for n, e, b in corpus_seeds()]
    return json.dumps(seeds, indent=2) + "\n"
