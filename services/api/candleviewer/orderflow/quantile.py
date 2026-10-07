"""Bounded-memory streaming quantiles for the big-trade percentile threshold (E22-T01).

**Estimator.** Extended P² (Jain & Chlamtac 1985; Raatikainen 1987 multi-marker form): a fixed
set of markers per quantile, O(1) state and work per sample, never stores samples.
**Trimmed wrapper (SR-E22-14):** once initialised, an input is
winsorised to `trim_factor *` the upper-middle marker before it reaches the extreme marker, so a
single outlier cannot drag the markers. Ranks are unaffected: a clamped sample still lands in
the top cell, so the q-marker's rank error (the ≤ 1 % target) is preserved.

**Trailing window by bucketed sub-estimators.** P² cannot delete samples, so the window is
split into `buckets` print-time slots of `window_us / buckets`, each with its own P² pair
(primary q + p80 for the over-flagging cap) and counts. Whole slots expire as print time
advances (O(1) amortised); the window is therefore the last `buckets` slots, aligned to slot
boundaries (worst case it covers one slot less than `window_us`). Window quantiles invert the
count-weighted mixture of each slot's piecewise-linear marker CDF by bisection. Accuracy
degrades with intra-window non-stationarity across slots; state is fixed at
`buckets * 2 * (grid + 4)` markers per symbol regardless of print rate."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from itertools import pairwise


class P2Quantile:
    """Extended P² (Raatikainen 1987): the classic five markers plus a fixed grid of
    `grid` evenly spaced marker fractions, all updated with the P² parabolic rule. More
    markers tighten the piecewise-parabolic CDF; classic 5-marker P² misses a 1 % rank target
    near q≈0.8-0.9 on heavy-tailed notionals. State stays fixed: `grid + 4` markers or fewer."""

    __slots__ = ("_dn", "_h", "_k", "_n", "_q", "_qi", "_trim")

    def __init__(self, q: float, *, trim_factor: float = 4.0, grid: int = 24) -> None:
        if not 0.0 < q < 1.0:
            raise ValueError("quantile must be in (0, 1)")
        self._q, self._trim = q, trim_factor
        fr = sorted({0.0, q / 2, q, (1 + q) / 2, 1.0, *(i / grid for i in range(1, grid))})
        self._dn, self._qi, self._k = fr, fr.index(q), len(fr)
        self._h: list[float] = []
        self._n = [float(i + 1) for i in range(self._k)]

    @property
    def count(self) -> int:
        return len(self._h) if len(self._h) < self._k else int(self._n[-1])

    def add(self, x: float) -> None:
        h, k = self._h, self._k
        if len(h) < k:
            h.append(x)
            h.sort()
            return
        top = h[k - 2]
        if top > 0:
            x = min(x, top * self._trim)  # SR-E22-14 winsorise
        if x < h[0]:
            h[0], c = x, 0
        elif x >= h[-1]:
            h[-1], c = x, k - 2
        else:
            c = bisect_right(h, x) - 1
        n, dn = self._n, self._dn
        for i in range(c + 1, k):
            n[i] += 1
        span = n[-1] - 1.0  # desired position of marker i is 1 + span * dn[i] (closed form)
        for i in range(1, k - 1):
            ni = n[i]
            d = 1.0 + span * dn[i] - ni
            if -1.0 < d < 1.0:
                continue
            nl, nr = n[i - 1], n[i + 1]
            if (d >= 1 and nr - ni > 1) or (d <= -1 and nl - ni < -1):
                s = 1.0 if d > 0 else -1.0
                hl, hi, hr = h[i - 1], h[i], h[i + 1]
                hp = hi + s / (nr - nl) * (
                    (ni - nl + s) * (hr - hi) / (nr - ni) + (nr - ni - s) * (hi - hl) / (ni - nl)
                )
                if not hl < hp < hr:
                    hp = hi + s * ((hr - hi) / (nr - ni) if s > 0 else (hl - hi) / (nl - ni))
                h[i], n[i] = hp, ni + s

    def markers(self) -> list[tuple[float, float]]:
        """(height, 1-based position) pairs; exact order statistics below 5 samples."""
        if len(self._h) < self._k:
            return [(v, float(i + 1)) for i, v in enumerate(self._h)]
        return list(zip(self._h, self._n, strict=True))

    def value(self) -> float:
        h = self._h
        if len(h) < self._k:
            return h[min(len(h) - 1, int(self._q * len(h)))]
        return h[self._qi]

    def cdf(self, x: float) -> float:
        """Fraction of samples ≤ x from the piecewise-linear marker interpolation."""
        m = self.markers()
        total = m[-1][1]
        if x < m[0][0]:
            return 0.0
        if x >= m[-1][0]:
            return 1.0
        for (h0, p0), (h1, p1) in pairwise(m):
            if h0 <= x < h1:
                return (p0 + (p1 - p0) * (x - h0) / (h1 - h0)) / total
        return 1.0  # pragma: no cover - unreachable: x within [m0, m-1)


@dataclass(slots=True)
class _Slot:
    index: int
    primary: P2Quantile
    secondary: P2Quantile
    count: int = 0
    flagged: int = 0


@dataclass(slots=True)
class WindowedQuantiles:
    q: float
    window_us: int
    buckets: int
    trim_factor: float = 4.0
    secondary_q: float = 0.80
    _slots: deque[_Slot] = field(default_factory=deque)
    _oldest: int = 0

    def __post_init__(self) -> None:
        if self.buckets < 1 or self.window_us < self.buckets:
            raise ValueError("buckets must be >= 1 and <= window_us")
        P2Quantile(self.q)

    @property
    def width(self) -> int:
        return self.window_us // self.buckets

    @property
    def count(self) -> int:
        return sum(s.count for s in self._slots)

    @property
    def flagged(self) -> int:
        return sum(s.flagged for s in self._slots)

    def oldest_ts_us(self) -> int:
        return self._oldest

    def expire(self, now_us: int) -> None:
        first = now_us // self.width - self.buckets + 1
        self._oldest = max(self._oldest, first * self.width)
        while self._slots and self._slots[0].index < first:
            self._slots.popleft()

    def add(self, ts_us: int, value: float, *, flagged: bool) -> None:
        self.expire(ts_us)
        idx = ts_us // self.width
        if not self._slots or self._slots[-1].index < idx:
            t = self.trim_factor
            self._slots.append(
                _Slot(
                    idx,
                    P2Quantile(self.q, trim_factor=t),
                    P2Quantile(self.secondary_q, trim_factor=t),
                )
            )
        slot = self._slots[-1]  # late print (bus order guarantee broken): joins newest slot
        slot.primary.add(value)
        slot.secondary.add(value)
        slot.count += 1
        slot.flagged += int(flagged)

    def max_marker(self) -> float:
        return max(s.primary.markers()[-1][0] for s in self._slots)

    def quantile(self, *, primary: bool) -> float | None:
        ests = [(s.primary if primary else s.secondary, s.count) for s in self._slots]
        ests = [(e, c) for e, c in ests if c]
        if not ests:
            return None
        if len(ests) == 1:
            return ests[0][0].value()
        target = self.q if primary else self.secondary_q
        total = sum(c for _, c in ests)
        lo = min(e.markers()[0][0] for e, _ in ests)
        hi = max(e.markers()[-1][0] for e, _ in ests)
        for _ in range(60):
            mid = (lo + hi) / 2
            if sum(e.cdf(mid) * c for e, c in ests) / total < target:
                lo = mid
            else:
                hi = mid
        return hi
