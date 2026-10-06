"""E17-K01 spike wire codecs: the three wire encodings of the ADR-0005 comparison.

Arm A  JSON envelope + structured (14.x schema) payload          (orjson)
Arm B  MessagePack envelope + the same structured payload         (msgpack)
Arm C  MessagePack envelope + fixed-layout binary blob (23-ws 3.4) (struct)

THROWAWAY harness code (ticket "Out of scope: production code"). Record sizes follow the
*field lists* of 23-ws-protocol.md 3.4, which disagree with the prose byte counts for bars
(fields sum to 65, doc says 69) and footprint cells (29, doc says 33) - see the finding note.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import msgpack  # type: ignore[import-untyped]  # venv ships msgpack without stubs; spike-only
import orjson

PRICE_SCALE = 1
QTY_SCALE = 3
MAGIC = 0x43565742
HEADER = struct.Struct("<IBBBBB3xIQ")  # 24 bytes
BOOK_REC = struct.Struct("<BqQ")  # 17
TRADE_REC = struct.Struct("<IqQBB")  # 22
BAR_REC = struct.Struct("<IqqqqQQIqB")  # 65 (doc prose says 69)
FP_GROUP = struct.Struct("<II")  # 8
FP_CELL = struct.Struct("<qQQIB")  # 29 (doc prose says 33)
HM_COL = struct.Struct("<IqqI")  # 24
HM_ROW = struct.Struct("<QQ")  # 16

KIND_BOOK_SNAP, KIND_BOOK_DELTA, KIND_TRADES, KIND_BARS, KIND_FOOTPRINT, KIND_HEATMAP = range(1, 7)


@dataclass(frozen=True)
class Frame:
    """One logical server->client data frame, in structured and binary form."""

    kind: str  # book_snap | book_delta | trades | bars | footprint | heatmap
    topic: str
    seq: int
    ts: int
    struct_payload: dict[str, Any]
    body: bytes  # 23-ws 3.4 binary body (header + records)
    flat: tuple[int, ...]  # canonical flattened integers (equivalence ground truth)


def dec(value: int, scale: int) -> str:
    """Scaled integer -> decimal string, e.g. (6311999, 1) -> '631199.9'."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if scale == 0:
        return f"{sign}{v}"
    return f"{sign}{v // 10**scale}.{v % 10**scale:0{scale}d}"


def undec(text: str, scale: int) -> int:
    return int(Decimal(text).scaleb(scale))


def header(kind: int, count: int, ts_base: int, flags: int = 0) -> bytes:
    return HEADER.pack(MAGIC, 1, kind, flags, PRICE_SCALE, QTY_SCALE, count, ts_base)


def envelope(f: Frame, enc: str) -> dict[str, Any]:
    base: dict[str, Any] = {"t": "snap" if f.kind == "book_snap" else "d", "ch": f.topic}
    base.update({"s": f.seq, "ts": f.ts})
    if enc == "b":
        base.update({"e": "b", "p": f.body})
    else:
        base.update({"e": "j", "p": f.struct_payload})
    return base


def encode_json(f: Frame) -> bytes:
    return orjson.dumps(envelope(f, "j"))


def encode_msgpack(f: Frame) -> bytes:
    out: bytes = msgpack.packb(envelope(f, "j"), use_bin_type=True)
    return out


def encode_binary(f: Frame) -> bytes:
    out: bytes = msgpack.packb(envelope(f, "b"), use_bin_type=True)
    return out


ARMS = {"json": encode_json, "msgpack": encode_msgpack, "binary": encode_binary}


CHECK_MOD = 1_000_003


def checksum(flat: tuple[int, ...] | list[int]) -> tuple[int, int, int]:
    """(count, sum mod M, index-weighted sum mod M): order-sensitive and exact in JS float64."""
    m = CHECK_MOD
    return (
        len(flat),
        sum(v % m for v in flat) % m,
        sum((i + 1) * (v % m) for i, v in enumerate(flat)) % m,
    )


def decode_body(body: bytes) -> tuple[int, ...]:
    """Binary body -> canonical flat integers (must equal Frame.flat)."""
    magic, ver, kind, _fl, _ps, _qs, count, base = HEADER.unpack_from(body, 0)
    if magic != MAGIC or ver != 1:
        raise ValueError("bad magic/version")
    off = HEADER.size
    out: list[int] = []
    if kind in (KIND_BOOK_SNAP, KIND_BOOK_DELTA):
        recs = [BOOK_REC.unpack_from(body, off + i * BOOK_REC.size) for i in range(count)]
        bids = [(p, q) for s, p, q in recs if s == 0]
        asks = [(p, q) for s, p, q in recs if s == 1]
        out += [len(bids), len(asks)]
        for p, q in bids + asks:
            out += [p, q]
    elif kind == KIND_TRADES:
        out.append(count)
        for i in range(count):
            o, p, q, side, fl = TRADE_REC.unpack_from(body, off + i * TRADE_REC.size)
            out += [base + o, p, q, side, fl]
    elif kind == KIND_BARS:
        out.append(count)
        for i in range(count):
            o, op, hi, lo, cl, v, tn, tr, de, fl = BAR_REC.unpack_from(body, off + i * BAR_REC.size)
            out += [base + o, op, hi, lo, cl, v, tn, tr, de, fl]
    elif kind == KIND_FOOTPRINT:
        out.append(count)
        for _ in range(count):
            o, n = FP_GROUP.unpack_from(body, off)
            off += FP_GROUP.size
            out += [base + o, n]
            for _c in range(n):
                p, b, a, tr, fl = FP_CELL.unpack_from(body, off)
                off += FP_CELL.size
                out += [p, b, a, tr, fl]
    elif kind == KIND_HEATMAP:
        o, pmin, pstep, rows = HM_COL.unpack_from(body, off)
        off += HM_COL.size
        out += [base + o, pmin, pstep, rows]
        for _r in range(rows):
            b, a = HM_ROW.unpack_from(body, off)
            off += HM_ROW.size
            out += [b, a]
    else:
        raise ValueError(f"unknown kind {kind}")
    return tuple(out)
