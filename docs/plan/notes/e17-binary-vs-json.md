# E17-K01 — binary vs JSON on the reference workspace (ADR-0005 gate)

Spike E17-K01 (GitHub #376). Harness: `tests/perf/ws/` (`python tests/perf/ws/run_all.py`),
evidence artefact: `tests/perf/ws/results.json`. Owner approval of the verdict: **pending**
(the deciders named in ADR-0005 collapse to the owner per the agent-delivery adaptations).

## 1. Verdict

| Gate criterion (ADR-0005 Validation)                      | Measured                                                                         | Verdict                    |
| --------------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------- |
| Decode time, binary vs JSON, >= 30 %                      | **-82.3 %** CPU (workspace-weighted, 4 panes); footprint -88 %, book delta -17 % | **PASS**                   |
| Bandwidth, binary vs JSON, >= 40 % — compression per §3.5 | binary raw 50.4 KiB/s vs JSON+deflate 23.7 KiB/s = **+112 % (binary is larger)** | **FAIL**                   |
| Bandwidth, like-for-like uncompressed                     | binary 50.4 vs JSON 153.6 KiB/s = **-67.2 %**                                    | PASS (not the spec regime) |

**Gate: NOT MET as specified** (one of two criteria fails under the compression regime that ADR-0005 /
`23-ws-protocol.md` §3.5 and the ticket's arm 1 prescribe). The honest reading is more nuanced than
PASS/FAIL, and the owner should decide knowing this:

1. The result is decided by **permessage-deflate with context takeover**, not by the encoding. Deflated
   with takeover, binary is -89.7 % vs deflated JSON (2.4 vs 23.7 KiB/s); deflated _without_ takeover
   (one sync-flushed message at a time) binary is only -29 % (20.1 vs 28.3 KiB/s) — below the gate.
2. Context takeover costs per-connection compressor state and defeats ADR-0005's "one encode, many sends"
   driver (each client's deflate stream is distinct). That cost was not measured here.
3. **Every arm is far inside the §16.3 bandwidth budget** (< 350 KiB/s): raw JSON is 154 KiB/s. And JSON
   decode of the whole workspace costs 0.76 ms of CPU per second (0.08 % of a core), with the worst frame
   (footprint 400 cells) at p99 0.35 ms vs the 1.0 ms target. The ADR's premise that JSON parsing
   "dominates the frame budget" is **not supported** on this workload; the relative win is real, the
   absolute win is ~0.6 ms/s.
4. **MessagePack with the structured payload is the worst arm** for decode (+108 % vs JSON.parse; the
   `@msgpack/msgpack` JS decoder loses to the native `JSON.parse`) and only -26 % raw bandwidth. This
   validates ADR-0005's rejection of "MessagePack everywhere" and warns against using msgpack structured
   payloads for anything hot (the "mid-tier" use must stay low-volume).

Recommendation (follow-on, for owner ratification — see the ADR-0005 amendment): the data plane **stays
JSON** (`cv.v1.json`, deflate on, the already-negotiated fallback) for the first release; the binary
codec (E17-T02) is **re-scoped to the two kinds where binary matters — footprint (kind 5) and heatmap
(kind 6) plus book snapshots (kind 1)** — as an opt-in `binary: true` capability, and ships only if the
owner accepts per-connection deflate-with-takeover on it. Nothing here is a reason to drop the schema-first
codec generation.

## 2. Method

**Workload** (`workload.py`, seed 17001, 60 s of stream, 2 401 frames). The 4-pane reference workspace of
§16.3 at the §6.1 default throttles: `book.BTCUSDT.50` @ 50 ms, `trades` @ 100 ms, `bars` (1 m) @ 250 ms,
`footprint` (5 m, **400 cells**) @ 250 ms. The "with heatmap" variant adds `heatmap.BTCUSDT` @ 500 ms
with 512 rows (ADR-0005 context). Book deltas take their per-frame change counts and quantities from the
recorded corpus `packages/fixtures/bybit/2026-10-05/ws/orderbook_BTCUSDT.jsonl` (mean 4.95 changes/side/
frame; 10 % deletions); trade prints replay `clean_publicTrade_BTCUSDT.jsonl`. Bars, footprint and heatmap
values are seeded synthetic (the corpus has no bar/footprint stream). **The corpus is a documented-shape
assembly, not a live capture** (its READMEs say so), so rates and sizes are modelled, not observed.

**Arms** (`wire_codecs.py`): A) JSON envelope + structured §14 payload via `orjson`; B) MessagePack
envelope + the same structured payload via `msgpack` 1.2.2; C) MessagePack envelope + §3.4 fixed-layout
binary blob. Arm C is hand-written for the six kinds (the ticket allows four). No `msgspec` is installed
in the repo venv and no production WS encoder exists yet (`candleviewer/ws/` has gateway/limits only), so
`orjson` (fastest JSON available — the ticket's confounder) and `msgpack` stand in.

**Bandwidth.** Per-message bytes + 2/4-byte unmasked WS frame header, summed over 60 s. Deflate arms use
`zlib` level 6, raw deflate with sync flush per message, with context takeover (RFC 7692 default; one
compressor per connection) and, separately, without takeover. Caveat: bytes are computed on the encoded
message, **not measured at a socket** as the ticket specifies (no network allowed); TCP/TLS framing is
excluded for all arms equally.

**Decode time** (`run_browser.mjs`): headless Chromium (chrome-headless-shell 153.0.8010.12, V8) via
playwright-core, run through the chart-engine bench toolchain (`machine.mjs`, `stats.mjs`; not the
frame-time scene runner, which models GPU cost and has no decode notion). Timed region = the decode
function only; each frame is timed in a calibrated loop (>= 1.5 ms per region because Chromium coarsens
`performance.now()` to ~0.1 ms/ 5 µs steps), 60 distinct frames per kind, 3 warm-up passes, **median of 5
runs** of per-run p50/p95/p99. Decoders: `JSON.parse` on the text frame; `@msgpack/msgpack` 3.1.3
(vendored UMD, ISC, not added to the lockfile — throwaway) for B; msgpack envelope + a `DataView`
struct-of-arrays reader for C (`Float64Array` columns; 64-bit ints via two 32-bit reads, exact below 2^53).
Outside the timer, **every decoded frame is checked for equivalence** against the Python canonical flat
integers (count/sum/weighted-sum checksum) — all frames pass in all three arms. Python also asserts
binary == canonical for all 2 401 frames and JSON-payload == msgpack-payload.

**Workspace decode cost** = sum over kinds of (p50 µs per frame x frames/s) -> ms of CPU per second.

## 3. Raw numbers (machine: i7-8550U 4C/8T 1.8 GHz, 15.9 GB, Windows 11; Python 3.12.3, Node 20.14)

### 3.1 Bandwidth — 4-pane reference workspace (KiB/s on the wire)

| Arm                       | Raw   | Deflate + takeover | Deflate, no takeover |
| ------------------------- | ----- | ------------------ | -------------------- |
| JSON (orjson)             | 153.6 | 23.7               | 28.3                 |
| MessagePack structured    | 113.6 | 3.7                | 26.8                 |
| MessagePack + binary body | 50.4  | 2.4                | 20.1                 |

With the heatmap pane: JSON 164.8 / 27.5 / 32.1; msgpack 131.9 / 18.1 / 31.9; binary 66.6 / 6.0 / 23.6.
Raw by kind (JSON -> binary, KiB/s): footprint 144.0 -> 45.7; book delta 4.8 -> 3.0; trades 3.4 -> 1.0;
bars 1.2 -> 0.55. The footprint pane is 94 % of the JSON bytes. Deflate-with-takeover collapses the
footprint (the 400-cell frame repeats ~385 unchanged cells every 250 ms), which is why compressed JSON is
so small — a property of this workload's high redundancy (15 of 400 cells change per update).

### 3.2 Browser decode, per frame, median of 5 runs (µs; p50 / p99)

| Kind (frames/s)      | JSON.parse    | msgpack-js structured | binary SoA   | binary vs JSON p50 |
| -------------------- | ------------- | --------------------- | ------------ | ------------------ |
| book delta (20)      | 1.8 / 3.5     | 3.3 / 7.4             | 1.5 / 2.4    | -17 %              |
| trades (10)          | 1.8 / 4.1     | 4.5 / 9.8             | 1.6 / 3.9    | -11 %              |
| bars (4)             | 1.7 / 3.7     | 3.7 / 10.9            | 2.1 / 3.5    | +23 % (slower)     |
| footprint 400 c (4)  | 175.0 / 350.0 | 362.5 / 775.0         | 20.3 / 193.8 | -88 %              |
| heatmap 512 r (2)    | 39.1 / 68.8   | 20.3 / 50.0           | 13.3 / 260.9 | -66 %              |
| book snapshot 50 (1) | 20.3 / 20.3   | 32.8 / 32.8           | 5.1 / 5.1    | -75 %              |

Workspace decode CPU: JSON 0.76, msgpack 1.58, binary 0.13 ms/s (4 panes); 0.84 / 1.62 / 0.16 with heatmap.
§16.3 targets: book delta < 0.15 ms p99 — **all three arms pass by ~40x** (p99 <= 0.01 ms); footprint
< 1.0 ms p99 — **all three pass** (JSON 0.35 ms, binary 0.19 ms). The binary p99 tails (footprint, heatmap)
are GC/timer noise of the Float64Array allocations on a 5 µs-resolution clock, and are larger than p50 by
~10-20x; treat p99 as an upper bound, not a point estimate.

### 3.3 Server cost (Python, µs per frame, median)

| Kind       | JSON (orjson) enc | msgpack enc | binary (envelope only) enc | binary body build (struct) | JSON dec | binary dec (numpy views) |
| ---------- | ----------------- | ----------- | -------------------------- | -------------------------- | -------- | ------------------------ |
| book delta | 1.5               | 4.4         | 2.5                        | ~2.4 / 10 levels           | 1.5-2.4  | 2.0                      |
| footprint  | 67.8              | 245.1       | 3.0                        | **96.8 (400 cells)**       | 167.9    | 3.0                      |
| heatmap    | 33.9              | 34.8        | 3.2                        | **102.5 (512 rows)**       | 34.9     | 2.9                      |

"Envelope only" excludes building the §3.4 body. A scalar `struct.pack` loop (what this harness does)
costs 97-103 µs for the big kinds, i.e. **slower than orjson on the whole structured frame** (68 / 34 µs);
production would need numpy structured arrays or a native codec to realise the encode win. Server encode
CPU therefore does **not** favour binary unless the codec is vectorised. GC pressure (the ticket's
allocated-bytes/s metric) was **not measured** (no `--expose-gc`/heap-sampling hook in this harness).

## 4. W2 — `book.BTCUSDT.500` vs 200 at the 100 ms cadence

30 s of deltas per depth at 10 frames/s (`workload.w2_streams`). Fixture changes are uniform over depth,
so the realistic case scales changed levels with depth (500 -> 2.5x the depth-200 delta); the lower bound
holds changed levels constant.

| Depth | JSON KiB/s (raw / deflate) scaled | Binary KiB/s (raw / deflate) scaled | Snapshot bytes JSON / binary | Browser decode p50 / p99 µs JSON (scaled) | Binary (scaled) |
| ----- | --------------------------------- | ----------------------------------- | ---------------------------- | ----------------------------------------- | --------------- |
| 50    | 1.9 / 0.3                         | 1.1 / 0.3                           | 2 268 / 1 791                | 1.6 / 3.7                                 | 1.7 / 3.0       |
| 200   | 2.7 / 0.5                         | 1.8 / 0.5                           | 8 570 / 6 892                | 2.0 / 4.5                                 | 2.3 / 3.9       |
| 500   | 4.7 / 1.0                         | 3.4 / 0.9                           | 21 170 / 17 092              | 7.0 / 12.5                                | 3.7 / 7.8       |

Constant-changes bound: depth 500 raw JSON 3.2 KiB/s, decode p99 5.1 µs. **Recommendation: keep depth
500** (no change to the §6.1 depth enum). Marginal cost over 200 is +2 KiB/s raw (+0.5 KiB/s deflated)
and ~+0.01 ms p99 decode, i.e. 1 % of the 0.15 ms book-delta budget and 0.6 % of the 350 KiB/s budget;
the 21 KB snapshot is 3 % of the 700 KiB re-snapshot budget. It stays opt-in per subscription so the
default workspace never pays it. Caveats: single-symbol, synthetic change distribution; the browser W2
medians are noisy at this scale (p50 of 1.8-7 µs on a 5 µs-resolution clock; the 500-depth JSON p50 varied
2.3-7.0 µs across harness runs) so read them as "sub-0.02 ms", not as a curve. No E21 re-cut is needed.

**Cadence correction.** ADR-0021 (E08-K01, measured) records Bybit's depth-500 tier at **200 ms**, not
100 ms; the 100 ms rows above are the worst case (the §6.1 default throttle for 200/500), and the real
upstream rate would roughly halve the 500-depth bandwidth. This note covers the **wire** cost only;
the ingestion/storage cost of depth 500 (CPU, GB/day) is ADR-0021's and is not re-opened here.

## 5. §16.3 budgets — restated as measured (laptop, modelled workload)

| Metric (§16.3)                              | Target        | Measured                                                                                                                                      |
| ------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Frame decode, book delta 50 levels          | < 0.15 ms p99 | JSON 0.004 ms; binary 0.002 ms (both pass ~40x)                                                                                               |
| Frame decode, footprint 400 cells           | < 1.0 ms p99  | JSON 0.35 ms; binary 0.19 ms (both pass; tail is timer/GC-bound)                                                                              |
| Server->client bandwidth, ref. workspace    | < 350 KiB/s   | JSON 154 raw / 24 deflated; binary 50 raw / 2.4 deflated (all pass 2.3-100x)                                                                  |
| Full re-snapshot of the reference workspace | < 700 KiB     | Not measured (needs the 200-bar footprint history + 2 000 heatmap columns); book.50 snapshot is 2.3 KB JSON — **unverified, left to E17-Q03** |
| Tick-to-pixel latency, 60 fps, resyncs/h    | —             | Out of scope (E17-Q03)                                                                                                                        |

## 6. Caveats and what would change the verdict

- **Laptop, not the §3.1 reference machine** (i7-8550U 4C/8T vs the 6C/12T / 32 GB class); headless
  Chromium, not Electron; no network, so no socket-level bandwidth; one JS engine version. Ticket AC
  "second engineer within 15 %": the five per-run p50s are published in `results.json`
  (`p50_runs_us`); footprint JSON p50 ranged 131-325 µs across the 5 runs (run 1 is ~2x slow — cold JIT / CPU
  boost; heatmap runs 1 and 5 likewise), so the 15 % bar holds only for the medians of 5 and for the large kinds, not for the 2-5 µs
  kinds. Variance source: Windows timer resolution + a thermally-limited 15 W laptop CPU.
- **Synthetic workload** (corpus is documented-shape; bars/footprint/heatmap fully synthetic). The
  deflate result is the most workload-sensitive number: a footprint pane whose cells change more than
  15 / 400 per update would compress far worse and move the no-takeover/takeover gap.
- The 400-cell footprint sends the **whole bar every 250 ms**; a delta footprint (only changed cells)
  would, as an unmeasured estimate (15 of 400 cells change per update), shrink JSON ~25x and erase most of the bandwidth case. This is the cheapest lever and is
  outside the three arms measured here.
- §3.4's prose record sizes (bars 69 B, footprint cell 33 B) disagree with its field lists (65 B and
  29 B); the harness follows the field lists. **E17-T02 must resolve this before writing the codec.**
- Not measured: GC pressure/allocated bytes per second, socket-level framing, Electron, server encode of a
  vectorised binary codec, per-connection cost of deflate takeover (memory + CPU at 8 connections x 40
  symbols).
- `msgpack` structured numbers use `@msgpack/msgpack` 3.1.3; `msgpackr` (faster, not vendored) would
  narrow the B-arm decode gap but not change the verdict (B is not the contender).

## 7. Reproduce

```sh
pnpm install --frozen-lockfile --ignore-scripts --offline
services/api/.venv/Scripts/python.exe tests/perf/ws/run_all.py   # ~2 min, offline, seed 17001
```

Requires the Playwright `chromium_headless_shell-1243` already installed; vendored decoder in
`tests/perf/ws/vendor/`. Output: `tests/perf/ws/results.json` (committed, ~26 KB).
