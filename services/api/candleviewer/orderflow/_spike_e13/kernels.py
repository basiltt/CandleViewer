"""E13-K01 SPIKE kernels (throwaway). Decimal at the boundary -> float64 inside.

Two forms per indicator, mirroring the TS worker kernels operation-for-operation:
* ``*_stream`` — scalar Python recurrence, same op order as the TS kernel (the parity candidate).
* ``*_np`` — vectorised numpy (the fast candidate); reassociates sums, so parity is epsilon-only.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
NAN = math.nan


class Bar(NamedTuple):
    t: int
    o: float
    h: float
    l: float  # noqa: E741 - OHLC convention
    c: float
    v: float


def from_decimal(t: int, o: Decimal, h: Decimal, l: Decimal, c: Decimal, v: Decimal) -> Bar:  # noqa: E741
    """Boundary conversion: Decimal -> float64 (exactly ``float(str)``, same as JS ``Number(str)``)."""
    return Bar(t, float(o), float(h), float(l), float(c), float(v))


def densify(bars: Sequence[Bar], step_ms: int = 60_000) -> list[Bar]:
    out: list[Bar] = []
    for b in bars:
        if out:
            p = out[-1]
            t = p.t + step_ms
            while t < b.t:
                out.append(Bar(t, p.c, p.c, p.c, p.c, 0.0))
                t += step_ms
        out.append(b)
    return out


def sma_stream(bars: Sequence[Bar], n: int = 20) -> dict[str, list[float]]:
    ring = [0.0] * n
    s = 0.0
    out: list[float] = []
    for i, b in enumerate(bars):
        k = i % n
        if i >= n:
            s -= ring[k]
        ring[k] = b.c
        s += b.c
        out.append(s / n if i >= n - 1 else NAN)
    return {"sma.sma": out}


class _Ema:
    def __init__(self, n: int) -> None:
        self.n, self.a, self.k, self.acc, self.v = n, 2 / (n + 1), 0, 0.0, NAN

    def push(self, x: float) -> float:
        if self.k < self.n:
            self.acc += x
            self.k += 1
            if self.k == self.n:
                self.v = self.acc / self.n
            return self.v
        self.v = (x - self.v) * self.a + self.v
        return self.v


def macd_stream(bars: Sequence[Bar], f: int = 12, s: int = 26, sig: int = 9) -> dict[str, list[float]]:
    ef, es, eg = _Ema(f), _Ema(s), _Ema(sig)
    m_o: list[float] = []
    g_o: list[float] = []
    h_o: list[float] = []
    for b in bars:
        fv, sv = ef.push(b.c), es.push(b.c)
        m = NAN if math.isnan(sv) else fv - sv
        g = NAN if math.isnan(m) else eg.push(m)
        m_o.append(m)
        g_o.append(g)
        h_o.append(NAN if math.isnan(g) else m - g)
    return {"macd.macd": m_o, "macd.signal": g_o, "macd.hist": h_o}


def ichimoku_stream(bars: Sequence[Bar], t: int = 9, k: int = 26, sb: int = 52) -> dict[str, list[float]]:
    qs = {(w, mx): deque[tuple[int, float]]() for w in (t, k, sb) for mx in (True, False)}

    def ext(i: int, w: int, mx: bool, x: float) -> float:
        q = qs[(w, mx)]
        while q and (q[-1][1] <= x if mx else q[-1][1] >= x):
            q.pop()
        q.append((i, x))
        while q[0][0] <= i - w:
            q.popleft()
        return q[0][1]

    res: dict[str, list[float]] = {f"ichimoku.{n}": [] for n in ("tenkan", "kijun", "spanA", "spanB", "chikou")}
    for i, b in enumerate(bars):
        ht, lt = ext(i, t, True, b.h), ext(i, t, False, b.l)
        hk, lk = ext(i, k, True, b.h), ext(i, k, False, b.l)
        hs, ls = ext(i, sb, True, b.h), ext(i, sb, False, b.l)
        tk = (ht + lt) / 2 if i >= t - 1 else NAN
        kj = (hk + lk) / 2 if i >= k - 1 else NAN
        res["ichimoku.tenkan"].append(tk)
        res["ichimoku.kijun"].append(kj)
        res["ichimoku.spanA"].append(NAN if math.isnan(kj) else (tk + kj) / 2)
        res["ichimoku.spanB"].append((hs + ls) / 2 if i >= sb - 1 else NAN)
        res["ichimoku.chikou"].append(b.c)
    return res


def vwap_stream(bars: Sequence[Bar], day_ms: int = 86_400_000) -> dict[str, list[float]]:
    names = ("vwap", "sd", "up1", "dn1", "up2", "dn2", "up3", "dn3")
    res: dict[str, list[float]] = {f"vwap.{n}": [] for n in names}
    day, sv, spv, spv2 = -1, 0.0, 0.0, 0.0
    for b in bars:
        d = b.t // day_ms
        if d != day:
            day, sv, spv, spv2 = d, 0.0, 0.0, 0.0
        tp = (b.h + b.l + b.c) / 3
        sv += b.v
        spv += tp * b.v
        spv2 += tp * tp * b.v
        if sv > 0:
            m = spv / sv
            var = spv2 / sv - m * m
            s = math.sqrt(var) if var > 0 else 0.0
            vals = [m, s, m + 1 * s, m - 1 * s, m + 2 * s, m - 2 * s, m + 3 * s, m - 3 * s]
        else:
            vals = [NAN] * 8
        for n, x in zip(names, vals, strict=True):
            res[f"vwap.{n}"].append(x)
    return res


STREAM = {"sma": sma_stream, "macd": macd_stream, "ichimoku": ichimoku_stream, "vwap": vwap_stream}


# ---- vectorised numpy forms (full recompute only) --------------------------------------------


def _cols(bars: Sequence[Bar]) -> tuple[npt.NDArray[np.int64], F64, F64, F64, F64]:
    a = np.asarray(bars, dtype=np.float64)
    return a[:, 0].astype(np.int64), a[:, 2], a[:, 3], a[:, 4], a[:, 5]


def sma_np(bars: Sequence[Bar], n: int = 20) -> dict[str, F64]:
    c = _cols(bars)[3]
    cs = np.concatenate(([0.0], np.cumsum(c)))
    out = np.full(c.size, NAN)
    out[n - 1 :] = (cs[n:] - cs[:-n]) / n
    return {"sma.sma": out}


def ichimoku_np(bars: Sequence[Bar], t: int = 9, k: int = 26, sb: int = 52) -> dict[str, F64]:
    from numpy.lib.stride_tricks import sliding_window_view as swv

    _, h, lo, c, _ = _cols(bars)

    def mid(w: int) -> F64:
        o = np.full(h.size, NAN)
        o[w - 1 :] = (swv(h, w).max(axis=1) + swv(lo, w).min(axis=1)) / 2
        return o

    tk, kj, spb = mid(t), mid(k), mid(sb)
    return {"ichimoku.tenkan": tk, "ichimoku.kijun": kj, "ichimoku.spanA": (tk + kj) / 2, "ichimoku.spanB": spb, "ichimoku.chikou": c}


def vwap_np(bars: Sequence[Bar], day_ms: int = 86_400_000) -> dict[str, F64]:
    t, h, lo, c, v = _cols(bars)
    tp = (h + lo + c) / 3
    day = t // day_ms
    start = np.r_[True, day[1:] != day[:-1]]
    seg = np.cumsum(start) - 1

    def segcum(x: F64) -> F64:
        cs = np.cumsum(x)
        base = np.r_[0.0, cs][np.flatnonzero(start)]
        return cs - base[seg]

    sv, spv, spv2 = segcum(v), segcum(tp * v), segcum(tp * tp * v)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.where(sv > 0, spv / sv, NAN)
        var = spv2 / sv - m * m
    s = np.where(var > 0, np.sqrt(np.where(var > 0, var, 0.0)), 0.0)
    s = np.where(sv > 0, s, NAN)
    r = {"vwap.vwap": m, "vwap.sd": s}
    for j in (1, 2, 3):
        r[f"vwap.up{j}"], r[f"vwap.dn{j}"] = m + j * s, m - j * s
    return r


# MACD is an IIR recurrence; there is no exact vectorised form, so the numpy path reuses the stream.
NP = {"sma": sma_np, "ichimoku": ichimoku_np, "vwap": vwap_np}
