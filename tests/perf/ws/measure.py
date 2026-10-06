"""E17-K01 server-side measurements: bandwidth, deflate, encode CPU, Python decode, W2.

Usage (from repo root, deterministic, offline):
    PYTHONPATH=tests/perf/ws services/api/.venv/Scripts/python.exe tests/perf/ws/measure.py
Writes tests/perf/ws/out/ (gitignored frame dumps for the browser decode run) and
tests/perf/ws/out/py-results.json; ``run_all.py`` merges it with the browser numbers.
"""

from __future__ import annotations

import base64
import json
import statistics
import sys
import time
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import msgpack  # type: ignore[import-untyped]
import numpy as np
import orjson

import wire_codecs as wc
import workload as wl

OUT = Path(__file__).resolve().parent / "out"
SECONDS = 60
SAMPLE_FRAMES = 60  # distinct frames per kind dumped for the browser run
DEFLATE_LEVEL = 6  # zlib default; what a stock permessage-deflate server negotiates


class WsDeflate:
    """permessage-deflate with context takeover (RFC 7692): shared window, sync flush."""

    def __init__(self, level: int = DEFLATE_LEVEL, takeover: bool = True) -> None:
        self.level, self.takeover = level, takeover
        self.c = zlib.compressobj(level, zlib.DEFLATED, -15)

    def size(self, data: bytes) -> int:
        if not self.takeover:
            self.c = zlib.compressobj(self.level, zlib.DEFLATED, -15)
        out = self.c.compress(data) + self.c.flush(zlib.Z_SYNC_FLUSH)
        return len(out) - 4  # RFC 7692 strips the trailing 00 00 FF FF


def ws_wire_bytes(payload_len: int) -> int:
    """Server->client WS frame overhead (unmasked): 2 B header, +2 / +8 for long payloads."""
    return payload_len + (2 if payload_len < 126 else 4 if payload_len < 65536 else 10)


def bandwidth(frames: list[wc.Frame], seconds: float) -> dict[str, Any]:
    res: dict[str, Any] = {}
    for arm, enc in wc.ARMS.items():
        raw = {"all": 0}
        dfl = {"all": 0}
        dfl_nt = {"all": 0}
        d_nt = WsDeflate(takeover=False)
        per_kind: dict[str, int] = defaultdict(int)
        d = WsDeflate()
        for f in frames:
            b = enc(f)
            raw["all"] += ws_wire_bytes(len(b))
            n = ws_wire_bytes(d.size(b))
            dfl["all"] += n
            dfl_nt["all"] += ws_wire_bytes(d_nt.size(b))
            per_kind[f.kind] += len(b)
        res[arm] = {
            "raw_kib_s": raw["all"] / 1024 / seconds,
            "deflate_kib_s": dfl["all"] / 1024 / seconds,
            "deflate_no_takeover_kib_s": dfl_nt["all"] / 1024 / seconds,
            "raw_by_kind_kib_s": {k: v / 1024 / seconds for k, v in sorted(per_kind.items())},
        }
    return res


def timeit(fn: Any, items: list[Any], reps: int = 15) -> float:
    """Median microseconds per item over ``reps`` full passes."""
    for it in items:
        fn(it)
    samples = []
    for _ in range(reps):
        t = time.perf_counter()
        for it in items:
            fn(it)
        samples.append((time.perf_counter() - t) / len(items) * 1e6)
    return statistics.median(samples)


NP_BOOK = np.dtype([("s", "u1"), ("p", "<i8"), ("q", "<u8")])
NP_TRADE = np.dtype([("o", "<u4"), ("p", "<i8"), ("q", "<u8"), ("s", "u1"), ("f", "u1")])
NP_CELL = np.dtype([("p", "<i8"), ("b", "<u8"), ("a", "<u8"), ("t", "<u4"), ("f", "u1")])
NP_ROW = np.dtype([("b", "<u8"), ("a", "<u8")])
NP_BAR = np.dtype(
    [("o", "<u4"), ("op", "<i8"), ("h", "<i8"), ("l", "<i8"), ("c", "<i8"), ("v", "<u8"),
     ("tn", "<u8"), ("tr", "<u4"), ("d", "<i8"), ("f", "u1")]
)  # fmt: skip


def np_decode_binary(buf: bytes) -> Any:
    env = msgpack.unpackb(buf, raw=False)
    body = env["p"]
    _m, _v, kind, _f, _ps, _qs, count, _base = wc.HEADER.unpack_from(body, 0)
    off = wc.HEADER.size
    if kind in (1, 2):
        return np.frombuffer(body, NP_BOOK, count, off)
    if kind == 3:
        return np.frombuffer(body, NP_TRADE, count, off)
    if kind == 4:
        return np.frombuffer(body, NP_BAR, count, off)
    if kind == 5:
        n = wc.FP_GROUP.unpack_from(body, off)[1]
        return np.frombuffer(body, NP_CELL, n, off + wc.FP_GROUP.size)
    rows = wc.HM_COL.unpack_from(body, off)[3]
    return np.frombuffer(body, NP_ROW, rows, off + wc.HM_COL.size)


def py_costs(frames: list[wc.Frame]) -> dict[str, Any]:
    by_kind: dict[str, list[wc.Frame]] = defaultdict(list)
    for f in frames:
        by_kind[f.kind].append(f)
    out: dict[str, Any] = {}
    for kind, fs in sorted(by_kind.items()):
        fs = fs[:SAMPLE_FRAMES]
        j = [wc.encode_json(f) for f in fs]
        m = [wc.encode_msgpack(f) for f in fs]
        b = [wc.encode_binary(f) for f in fs]
        out[kind] = {
            "encode_us": {
                "json_orjson": timeit(wc.encode_json, fs),
                "msgpack": timeit(wc.encode_msgpack, fs),
                "binary_envelope_only": timeit(wc.encode_binary, fs),
            },
            "decode_us": {
                "json_orjson": timeit(orjson.loads, j),
                "msgpack": timeit(lambda x: msgpack.unpackb(x, raw=False), m),
                "binary_numpy_views": timeit(np_decode_binary, b),
            },
        }
    # struct.pack body-build cost for the largest binary kinds (excluded from envelope-only).
    cells = [(1, 2, 3, 4, 0)] * 400
    rows = [(1, 2)] * 512
    out["_binary_body_build_us"] = {
        "footprint_400_cells": timeit(lambda c: b"".join(wc.FP_CELL.pack(*x) for x in c), [cells]),
        "heatmap_512_rows": timeit(lambda c: b"".join(wc.HM_ROW.pack(*x) for x in c), [rows]),
        "book_delta_10_levels": timeit(
            lambda n: b"".join(wc.BOOK_REC.pack(0, 1, 2) for _ in range(n)), [10]
        ),
    }
    return out


def assert_equivalence(frames: list[wc.Frame]) -> int:
    """Every frame: binary body decodes to the canonical flat == structured payload content."""
    n = 0
    for f in frames:
        if wc.decode_body(f.body) != f.flat:
            raise AssertionError(f"binary != canonical for {f.kind} seq {f.seq}")
        env_j = orjson.loads(wc.encode_json(f))
        env_m = msgpack.unpackb(wc.encode_msgpack(f), raw=False)
        if env_j["p"] != env_m["p"] and f.kind != "heatmap":
            raise AssertionError(f"json != msgpack payload for {f.kind} seq {f.seq}")
        env_b = msgpack.unpackb(wc.encode_binary(f), raw=False)
        if wc.decode_body(env_b["p"]) != f.flat:
            raise AssertionError(f"wire-binary != canonical for {f.kind}")
        n += 1
    return n


def dump_for_browser(frames: list[wc.Frame]) -> dict[str, Any]:
    OUT.mkdir(exist_ok=True)
    by_kind: dict[str, list[wc.Frame]] = defaultdict(list)
    for f in frames:
        by_kind[f.kind].append(f)
    manifest: dict[str, Any] = {}
    for kind, fs in sorted(by_kind.items()):
        fs = fs[:SAMPLE_FRAMES]
        manifest[kind] = {
            "checks": [list(wc.checksum(f.flat)) for f in fs],
            "arms": {
                arm: [base64.b64encode(enc(f)).decode() for f in fs] for arm, enc in wc.ARMS.items()
            },
        }
    (OUT / "browser-frames.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {k: len(v["checks"]) for k, v in manifest.items()}


def main() -> int:
    frames = list(wl.generate(SECONDS, heatmap=True))
    four_pane = [f for f in frames if f.kind != "heatmap"]
    equiv = assert_equivalence(frames)
    counts: dict[str, int] = defaultdict(int)
    for f in frames:
        counts[f.kind] += 1
    result: dict[str, Any] = {
        "seed": wl.SEED,
        "seconds": SECONDS,
        "deflate_level": DEFLATE_LEVEL,
        "frames_by_kind": dict(counts),
        "equivalence_frames_checked": equiv,
        "bandwidth_four_pane": bandwidth(four_pane, SECONDS),
        "bandwidth_with_heatmap": bandwidth(frames, SECONDS),
        "python_costs": py_costs(frames),
        "browser_dump_frames": dump_for_browser(frames),
    }
    w2 = {}
    for mode in (True, False):
        streams = wl.w2_streams(30, scale_with_depth=mode)
        w2["scaled_changes" if mode else "constant_changes"] = {
            name: {
                **{a: v for a, v in bandwidth(fr, 30).items()},
                "delta_frames": len(fr) - 1,
                "snapshot_bytes": {a: len(e(fr[0])) for a, e in wc.ARMS.items()},
            }
            for name, fr in streams.items()
        }
        for fr in streams.values():
            for f in fr[:40]:
                assert wc.decode_body(f.body) == f.flat
        w2[f"decode_us_{'scaled' if mode else 'constant'}"] = {
            name: {
                "json_orjson": timeit(orjson.loads, [wc.encode_json(f) for f in fr[1:61]]),
                "binary_numpy": timeit(np_decode_binary, [wc.encode_binary(f) for f in fr[1:61]]),
            }
            for name, fr in streams.items()
        }
        # browser dump for W2 (delta frames only), keyed by depth
        key = "scaled" if mode else "constant"
        dump = {
            name: {
                "checks": [list(wc.checksum(f.flat)) for f in fr[1:61]],
                "arms": {
                    a: [base64.b64encode(e(f)).decode() for f in fr[1:61]]
                    for a, e in wc.ARMS.items()
                },
            }
            for name, fr in streams.items()
        }
        (OUT / f"browser-w2-{key}.json").write_text(json.dumps(dump), encoding="utf-8")
    result["w2"] = w2
    (OUT / "py-results.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["bandwidth_four_pane"], indent=1)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
