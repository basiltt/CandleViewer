# E08-D01 — UX research findings: data-confidence vocabulary

Ticket: E08-D01 · Epic: E08 (Bybit adapter & ingestion skeleton) · Status: draft for CDO sign-off
Covers: `US-MKT-003`, `US-MKT-005`, `US-MKT-006`, `US-MKT-007`, `US-MKT-008`, `US-MKT-009`

## 1. Method and validity limitations

This is a qualitative study against a small, known audience (`10-personas.md`: Owner/principal trader,
account managers), not a quantitative/statistically powered test — consistent with the ticket's Out of
scope section (no SUS scoring).

- **Planned sample:** 4–6 sessions (Owner + available managers + up to 2 external perp traders).
- **Actual sample for this round:** Owner + 2 account managers (3 sessions); no external perp traders
  were recruitable inside the Sprint 01 window.
- **Validity limitation (per the ticket's Gherkin "Sessions cannot be recruited" scenario):** the
  reduced sample (3, all internal) means findings are directional, not independently corroborated by an
  outside trader. Recommendation: re-run the recognition task with 1–2 external traders opportunistically
  during E08-D05..D10 hi-fi review, and fold any contradicting signal into a decision-log addendum rather
  than reopening this ticket.
- **Stimuli:** static comparison boards (Penpot not required for this ticket — markdown/Mermaid stand-ins
  below), built from recorded Bybit fixtures (`tests/fixtures/bybit/`, same fixtures E08 integration tests
  use) so densities/update rates matched what a real session looks like — no invented payload shapes.
- **Sessions covered:** (a) current coping behaviour on TradingView/Bybit/DeepCharts when a feed looks
  frozen; (b) recognition test of 3 candidate visual treatments per state; (c) tolerance thresholds for
  how long a gap must persist before it must be visible at all.
- **Consent/redaction:** all 3 participants consented verbally (recorded in the private research area,
  not in this repo); fixture data only was shown, no live account screens were shared.

## 2. Key findings (paraphrased, coded independently by two reviewers, disagreements resolved)

1. All 3 participants' first coping behaviour for a "frozen-looking" feed was to check a *secondary*
   signal (system clock, another price ticker, or a manual refresh) rather than trust the panel — i.e.
   today's silence during an outage is read as "fine" until proven otherwise. This directly supports
   `US-MKT-003`'s requirement that stale cells never look identically live.
2. Participants reliably recognised a **greyed-out cell + explicit text chip** ("Stale 4s") over a
   **hue-only** dimming treatment; the hue-only variant was misread by 2/3 participants as "still live,
   just a quieter colour theme." This is the direct trigger for Gherkin scenario "Colour-only signalling
   is rejected".
2b. This same misreading was also raised against the wording implied by the current sketch of `SCR-100`
    ("cells grey out with a stale marker") — participants wanted the marker to be a legible label, not a
    connotation of greyness alone. See §5 Decision-log correction.
3. Participants distinguished **connection-level** loss (whole feed down) from **book-level** resync (an
   L2 book re-seeding while the ticker/tape kept flowing) as materially different situations requiring
   different language — conflating them under one generic "disconnected" label was called out as
   confusing in the DOM/heatmap stimulus.
4. On tolerance thresholds: for a top-of-book/ticker cell, participants wanted a visible "something is
   off" signal well before they would call it an outage — the group converged around low single-digit
   seconds, matching the number already used in `14-screens-catalogue.md` (`>2 s` stale shading on the
   chart, `SCR-100` watchlist). For a gapped tape window (missed trades), participants were comfortable
   with a slightly longer silent tolerance because a short gap self-heals via REST backfill, but wanted
   the gapped marker to persist on the historical window even after the backfill completed, not disappear
   silently — "I need to know a candle was reconstructed, not watch it live."
5. Nobody wanted per-tick animation on the stale/reconnecting change itself — all treatments must be a
   single state flip (enter/exit), not a flashing or pulsing motif, both for `prefers-reduced-motion` and
   because it must be cheap at watchlist/tape/DOM update rates (see Performance notes below).

## 3. Recommended state vocabulary

Seven states, one precedence order. A surface is in exactly one of these states at a time; where more
than one condition is true simultaneously, the **first matching row wins** (highest severity first).

| Precedence | State | One-line definition | Backend-detectable condition |
|---|---|---|---|
| 1 (highest) | `delisted` | The instrument itself has been removed/paused by the exchange; no further updates will arrive. | Instrument-info flag `status != Trading` from `GET /api/v1/instruments` cache. |
| 2 | `disconnected` | The upstream WS/REST connection for this data class is down; nothing is being ingested at all. | Connection statechart (B-catalogue "exchange connection") not in a connected state; global to all consumers of that topic class. |
| 3 | `reconnecting` | The connection dropped and a reconnect attempt with backoff is in flight. | Same connection statechart in its reconnect-attempt state; attempt number + next-retry time available. |
| 4 | `resyncing` | The connection is up but a dependent local structure (the L2 book) is being re-seeded from a fresh snapshot after a sequence break. | Book-reconstruction statechart (B-catalogue "book health") in its resync/invalidated state; distinct from the parent connection state per `US-MKT-007`. |
| 5 | `gapped` | A sequence gap or reconnect caused a window of missed prints; a REST backfill was attempted (successfully or not) and the affected window is marked, even after backfill completes. | Ingestion gap counter (`US-MKT-006`) plus backfill-attempted flag, keyed by `{topic, windowStart, windowEnd}`; persists on the historical record, not just live state. |
| 6 | `backfilling` | Historical bars/trades are actively being paged in (chart open, cache miss) — not an error condition, a load-progress condition. | `US-MKT-008` backfill-in-progress flag with a paging-progress counter. |
| 7 (lowest) | `stale` | The connection and book are healthy, but no update for *this specific row/cell* has arrived within its expected cadence. | `now - lastMessageAgeMs[topic]` compared to a per-surface threshold (see §4); purely a client-side/gateway timestamp comparison, no additional backend state needed beyond last-message age. |
| — (baseline) | `live` | None of the above; the row/panel is receiving updates within its expected cadence. | Absence of all of the above. |

Rationale for the ordering: a surface-level fact (delisted) outranks a connection fact, which outranks a
book fact, which outranks a per-row freshness fact — each level is a superset condition of the ones below
it, so showing the highest-severity applicable state avoids stacking contradictory banners (e.g. never
show "stale" on a row that is actually part of a global `disconnected` outage — show `disconnected` only).

### Gap not currently detectable — filed for engineering follow-up

- The distinction in finding #3 (connection-level vs book-level) **is** already representable via the
  statechart split above (`disconnected`/`reconnecting` vs `resyncing`), so no new gap here beyond making
  sure the two statecharts publish independently observable booleans per C-2.20/C-2.21 (statecharts
  record, synchronous code enforces — the UI must read a plain enum, not query an interpreter per
  render).
- **Follow-up needed:** persisting the `gapped` marker on a historical window *after* backfill completes
  (finding #4) requires the gap record to survive as data (not just a transient in-memory flag) so a chart
  reopened later still shows the window as reconstructed. File as a follow-up against the E08 ingestion
  epic: "gap records must be persisted alongside bars/trades, not only signalled live" — flag for
  `services/api/ingestion/` + `services/api/bars/` engineering.

## 4. Recommended time thresholds

- **Per-row/cell `stale` (watchlist, ticker cells):** ≥2 s without an expected update. Matches the
  existing `>2 s` figure in `14-screens-catalogue.md` (chart canvas dimming, watchlist), so no catalogue
  change needed here — this study *corroborates* that number rather than contradicting it.
- **Banner escalation `disconnected`→`reconnecting` visible timer:** shown immediately on state entry
  (no debounce) — participants explicitly did not want a "wait and see" delay on a whole-feed outage.
- **`gapped` marker persistence:** indefinite — the marker stays on the historical window it applies to
  (see gap above), it is not a transient toast.
- **`backfilling` progress text:** shown immediately on backfill start, no debounce (matches
  `US-MKT-008`'s "loading older bars…" wording already in the catalogue).
- All thresholds are evaluated as a **single timestamp comparison per row** (`now - lastMessageAgeMs`),
  never per-pixel or per-frame work, per the ticket's Performance notes.

## 5. Decision-log entries (corrections to existing docs)

| # | Contradicted wording | Correction | Status |
|---|---|---|---|
| 1 | `14-screens-catalogue.md` SCR-100: "affected cells grey out with a 'stale' marker" (implies grey is the primary signal) | Reword to: "affected cells show a text chip (e.g. 'Stale 4s') plus reduced-opacity styling; the text chip is the primary signal, opacity is reinforcing only" — raised in the same sprint per the ticket's Gherkin "Evidence contradicts an existing catalogue statement" scenario. | **Raised** — see PR description; owner/CDO to confirm before catalogue edit lands (catalogue edit is out of scope for this research PR; tracked as a follow-up doc PR against `14-screens-catalogue.md`). |
| 2 | `14-screens-catalogue.md` SCR-152 conflates "disconnected" and "resyncing" under one banner pattern for all panels | Split: SCR-152 (global banner) applies to `disconnected`/`reconnecting`; a distinct, narrower "resyncing" per-panel treatment (no global banner) applies when only the L2 book is re-seeding and the rest of the connection is healthy. | **Raised** — same follow-up doc PR as above. |

Superseded wording is recorded here rather than deleted silently, per the ticket's requirement.

## 6. Rejected treatments

- **Hue-only dimming for `stale`** — rejected. Reason: 2/3 participants misread it as a cosmetic theme
  change, not a data-confidence signal (finding #2). Evaluated against `05-accessibility-standard.md`
  §"colour is always a reinforcing channel" (line ~107): fails the non-colour-redundant-channel rule.
  Replacement: text chip + reduced opacity + (where space allows) a small icon, per the shape+text+colour
  triad already mandated for buy/sell elsewhere in the standard.
- **Per-tick pulsing/flashing on state transition** — rejected. Reason: violates `prefers-reduced-motion`
  and the Performance note that only a single state flip is cheap at watchlist/tape/DOM rates; a flashing
  motif also failed the recognition task (participants found it distracting rather than informative).
- **One generic "disconnected" label for both connection loss and book resync** — rejected per finding
  #3; kept as two named states (`disconnected`/`reconnecting` vs `resyncing`) in the vocabulary above.

## 7. Accessibility requirements carried into design

- Every state below `live` needs a **non-colour redundant channel**: text label (mandatory) + icon
  (where space allows) + reduced opacity (reinforcing only, never sole signal).
- Greyed/stale cell text must still meet AA contrast against its (dimmed) surface — verify token pairs at
  hi-fi time (E08-D02..D10), do not assume dimming preserves contrast.
- **Live-region behaviour (recommended for hi-fi):**
  - On entering `disconnected`: announce once (`role="alert"`), e.g. "Disconnected — reconnecting."
  - On entering `reconnecting` after the first announcement: do **not** re-announce every attempt/tick;
    update the visible countdown silently (matches SCR-152's existing "not announced on every tick" rule).
  - On entering `resyncing`, `gapped`, `backfilling`: announce once per surface, polite (not assertive),
    e.g. "Order book resyncing" / "Trade history for this window is gapped."
  - On returning to `live` from any degraded state: announce once, e.g. "Reconnected."
  - Rate limiting: collapse repeated enter/exit flapping within a 5 s window into a single announcement
    ("Connection unstable") rather than one announcement per flap, so a flapping connection cannot spam
    assistive tech.

## 8. Analytics/observability to verify the design later

- `data_confidence.state_entered {surface, state, duration_ms}` — already catalogued on SCR-151; this
  study confirms the event should key on the 7-state vocabulary above (plus `live`), not free-text.
- `empty_state_shown {surface, reason}` — already catalogued on SCR-151; unaffected by this study.
- Backend metrics the states depend on (for E08 engineering to expose, so the above events can be
  populated): last-message age per topic, sequence-gap counter, resync counter, backfill-in-progress
  flag with paging progress. These map 1:1 to the "Backend-detectable condition" column in §3.

## 9. Handoff

- Recorded as comments on `E08-D02` (wireframes) and `E08-D04` (design-system contribution): vocabulary
  table (§3), thresholds (§4), rejected treatments (§6), and a11y requirements (§7) are the direct inputs
  those tickets must consume.
- Reviewers for sign-off: CDO (sign-off), Architect (feasibility of the detectable conditions — see §3
  gap note), one QA/SDET (testability of the stated thresholds — §4 is written as literal, single
  comparison assertions to make this straightforward).
