# Meta-issue #26 — round-11 update: `main` @ `c78ce99` (unreleased 0.8.1)

**Round 11. Verified build:** `main` @ **`c78ce99`** (merge of PR #217 from `fix/0.8.1-round10`).
`__version__` still reports `0.8.0` on this tree — **identify this build by commit, never by version string.** CPython 3.13.7, Windows 11, fresh venv, all repros run from a neutral working directory.

**GATE DECISION: ADOPT WITH CONSTRAINTS — decision-table row 6**, down one row from round 10's row 8. Row 6 is "all Blockers closed, 1–5 High open, each with a mechanically enforced mitigation". The single open High is a memory leak, and the constraint that contains it is a lint rule we wrote last round for a different reason.

**Method:** 5 issue verifications re-run live; full regression sweep (gate, 163 checks, plus a 527-script sweep with every delta re-confirmed **serially**); diff review `19cb1f1..c78ce99`; 8 battle tracks; 20 contract machines driven end-to-end **on both service spellings**; triage → dedupe → **independent adversarial refutation of every Blocker and High**. Nothing counted without a standalone repro on a clean interpreter, and every service/action check run with both `def` and `async def`.

---

## Headline

**All five fixes land clean, on both engines and both service spellings — the second consecutive round with no "fixed on one axis only" residual anywhere in the corpus.**

- **#212's semantic reversal is exact, not approximate.** The measured `raise(delay=)` beat rate is indistinguishable from `after:` at every rung; 200 machines × 1 ms ping-pong for 10 s gives 0 trips and 0 drops; a 2000-cell livelock fuzz is clean; zero-delay cycles still trip.
- **#213's v3 round-trip is exact**: 600/600 trials carrying the right `remaining_ms` (±0.5 ms) and `send_id`, firing not early, not late, exactly once.
- **#214's strict-on-restore works** for `pending_events`, and its v2 upcast closes the 0.8.0 `after`-record migration cliff we reported last round.
- **#215's lap parity holds** on the shapes it pins, and `start()` descent-settle is bounded under 100 concurrent starts.
- **#216 is flawless at the level it checks** — 47/47, 120/120 and 200/200 mutation runs, with a correct did-you-mean every time.

**Zero true regressions** across 163 gate checks and 527 sweep scripts. The single stable PASS→FAIL delta is **our own test encoding the #206 rule that #212 deliberately reverses**; we have retired it rather than reporting it.

**Post-refutation the round leaves 0 Blocker · 1 High · 4 Medium · 5 Low.**

## Disposition of the 5 issues

| Disposition | Issues |
|---|---|
| **FIXED — closing** (5) | #212, #213, #214, #215, #216 |

No issue regressed and none is partially fixed. Four carry follow-up notes on their own threads — all of them **scope or composition gaps rather than failures of the mechanism that shipped**: #214 and #216 each fixed one level and left the adjacent one; #213 fixed the hop and left the second hop; #215 fixed the parity and added a gate.

## Two corrections we owe you

**We filed a Blocker against the v2 upcast and refuted it ourselves.** The mechanism reproduces exactly — editing one integer (`"version": 3` → `2`) gets forged `done`/`error`/`after` records minted as engine-authentic, firing a 60,000 ms `after` in ~1 ms with `last_error=None`. But the control killed it: **an attacker who can edit `version` can equally edit `state_ids` and land in the target state directly, with no event forgery at all.** `from_snapshot` is a documented trusted-input boundary; the upcast confers no privilege the payload lacked. We are not filing it as a vulnerability.

**We also refuted our own claim that #212 voids `maxIterations`.** We observed `raise(delay=0.0001)` spinning at ~20k laps/s outside the budget — but plain `after:` at the same delay behaves identically on the same charts, and has been exempt since long before #212. Nothing regressed; #212 achieved parity with a path the budget never bounded by design. It is also not a liveness failure: an external `send` during the spin is served in ~16 ms, the Windows timer floor.

**This is the third round running in which a Blocker filed against engine-event provenance was refuted by our own control probe.** We are adopting the check as a triage *precondition* rather than a refutation step: any finding whose threat model requires blob-write must first be tested against "what does the same writer achieve with `state_ids`/`context` alone?" If the answer is "the same thing", there is no defect. We would suggest the same test for any report of this shape you receive.

## The one thing that costs a row

**#212 opened no semantic hole — and it made a latent resource defect unbounded.**

`_timer_handles` retains one handle per `raise(delay=)` beat and nothing prunes it before `stop()`, because `_schedule_send` keys the handle under the *machine* id while the only pruner pops by *state* id on state exit. The `after:` path keys by state id and is pruned correctly — it is flat under identical load.

Before #212 this was invisible: #206's trip killed such a cycle at roughly `maxIterations` beats, capping retention at ~12 entries. Now the cycle is legal, so growth has no ceiling — **+455 MB / 24 s at 200 machines, strictly linear, no plateau**, on both engines and both action kinds, at exactly 1.00 handle per beat.

We attacked this from the "you are holding it wrong" direction first and could not find a usage that bounds it: id reuse, explicit `cancel(sendId)` before each re-arm, a 250 ms period and a never-exiting self-loop all retain 1.00/beat, because `_cancel` clears the clock and `_armed_self_sends` but never touches `_timer_handles`.

**The interaction is what makes it matter.** #212 explicitly endorses the shape that leaks, and #213 makes `raise(delay=)` the only restart-safe in-chart deadline primitive — so the documented path to snapshot-safe deadlines is currently also the leaking one, with no in-API way to avoid it.

**The fix appears to be one line per engine**, and the correct pattern already exists four hundred lines away in the `after` path (`owner_id=state.id`).

## New issues filed this round

| Severity | Title |
|---|---|
| **High** | `_timer_handles` grows by one retained entry per `raise(delay=)` beat and is never pruned |
| Medium | #215's `_descent_done` gate: an entry action awaiting its own receipt hangs `start()` forever, silently |
| Medium | #216 validates the root config only; a misspelled key inside a state is silently dropped even under `strict_config=True` |
| Medium | Restore then re-persist without `start()` silently drops every armed delayed self-send |
| Medium | A `RunawayChainError` chain trip reaches only `last_error`, and the next benign event erases it |

Each body carries a **standalone repro** (stdlib + `xstate_statemachine` only, all helpers inlined) that was executed from a neutral working directory against this commit, both before and after being embedded in the issue text. All five exit 1 on this build.

Lower-severity items raised as notes on the relevant threads rather than as issues: `on_invalid_event` unreachable on the restore path; `scheduled_sends` missing the strict check `pending_events` gets; `structure_hash` omitting `raise(delay=)` delays; `lane` unenforceable on the sync engine; the snapshot guide's `minimum_version=1` floor; and the `+2` / `+3` changelog contradiction.

## What we would suggest prioritising

1. **The `_timer_handles` pruning** — the only open High, one line per engine, and it dissolves the deadline-primitive dilemma entirely.
2. **Bound or reorder the `_descent_done` gate** — a silent unbounded hang inside `start()` is the worst failure shape for anything supervised.
3. **Recurse the config key check** — the machinery, the hint and the strict switch all already exist and work; the recursion roughly multiplies their value.

Items 4–8 (the `scheduled_sends` union, routing re-arm through `_admit_restored`, a sticky chain-trip counter, `plugins=` on `from_snapshot`, and the doc fixes) all look small.

**This is the most tractable defect list the series has produced** — six of the eight are one-liners. Our position is one row worse than last round because the release made a legal usage that leaks; the release itself is better than the one before it.

## One request, and one thank-you

**Request:** the `+2` / `+3` plateau numbers in the changelog are each correct for a *different* shape (descent-seeded gets `+3`, externally kicked gets exactly `+2` — we swept limits {3,5,7,9} to confirm). One sentence distinguishing them would prevent budget sizing that under-provisions the descent case by ~2.7×, which is a mistake we made ourselves.

**Thank-you:** the round-9 ask to parametrise service-invoking tests over `def` / `async def` continues to pay. **The service-kind axis has now been flat across our entire corpus for two consecutive rounds.** That change retired a whole class of finding.

## Where this leaves us

Post-refutation the round closes at **0 Blocker · 1 High · 4 Medium · 5 Low**, one row worse than round 10's clean 0/0/5/7 — the High is R11-04, mechanically contained by CV-C47 (a lint written last round for a different finding, now load-bearing on new ground), not an open, unmitigated defect.

**Trend, round 5 → round 11:**

| Round | Commit | Blocker | High | Medium | Low |
|---|---|---|---|---|---|
| 5 | `3ed3099` | 4 | 8 | 8 | 1 |
| 6 | `cec108b` | 2 | 2 | 7 | 9 |
| 7 | `221ce7c` | 2 | 4 | 6 | 8 |
| 8 | `6db65d8` | 1 | 3 | 7 | 4 |
| 9 | `f28719c` | 0 | 2 | 5 | 8 |
| 10 | `19cb1f1` | 0 | 0 | 5 | 7 |
| 11 | `c78ce99` | 0 | 1 | 4 | 5 |

**0 Blocker holds for the third consecutive round.** The single reopened High is a resource leak the release itself created by fixing a correctness defect (#212 removed the trip that had, as a side effect, been capping `_timer_handles` retention); it is not a reversion of any prior security or correctness finding — R11-01/R11-02/R11-03/R11-05 all round-trip back down to refuted, downgraded, refuted, and refuted respectively. Every prior round's closed Blocker and closed High stays closed.

## Full checklist, #27–#216, by status

Every issue we have ever filed against this library, round 1 through round 11. `closed` means confirmed fixed and holding on this round's re-verification (or, for issues predating round 6, never regressed on any later round's regression sweep). Issues carrying a residual are cross-linked to the `R{n}-nn` finding that narrows or continues them.

| Status | Issues |
|---|---|
| **closed** (round 1–3, #27–#98) | #27 #28 #29 #30 #31 #32 #33 #34 #35 #36 #37 #38 #39 #40 #41 #42 #43 #44 #45 #46 #47 #48 #49 #50 #51 #52 #53 #54 #55 #56 #57 #58 #59 #60 #75 #76 #77 #78 #79 #80 #84 #85 #86 #87 #88 #89 #90 #91 #92 #93 #94 #95 #96 #97 #98 |
| **closed** (round 4–5, #99–#145) | #99 #102 #103 #104 #105 #106 #107 #108 #109 #110 #111 #112 #113 #114 #115 #116 #117 #118 #119 #120 #121 #123 #124 #125 #126 #127 #128 #129 #130 #131 #132 #133 #134 #135 #136 #137 #138 #142 #143 #144 #145 |
| **closed** (round 6–7, #146–#178) | #146 #147 #148 #149 #150 #151 #152 #153 #154 #155 #156 #157 #158 #159 #160 #161 #162 #163 #164 #165 #166 #169 #170 #171 #172 #173 #176 #177 #178 |
| **closed** (round 8, #179–#191) | #179 #180 #182 #183 #184 #185 #187 #188 #189 #190 #191 |
| **closed** (round 9, #181 #186 #192 #194 #196 #198 #199 #200 #201) | #181 #186 #192 #194 #196 #198 (residual `R9-14`, Low) #199 (residual `R9-15`, Low) #200 #201 (residual `R9-09`, Medium/doc) |
| **closed** (round 10, #203–#210) | #203 (residual `R10-05` → #214, Medium) · #204 (no residual) · #205 (residual, folded into hardening notes) · #206 (residual `R10-03` → #212, Medium; **now `SUPERSEDED-RULE`, see below**) · #207 (two residuals, Low) · #208 (changelog overstatement, Low) · #209 (residual `R10-06` → #215, Medium) · #210 (residual, `+2`/`+3` changelog contradiction, Low — **settled this round, still a doc fix**) |
| **closed** (round 11, #212–#216) | #212 (residual `R11-04`, High) · #213 (residual `R11-08`, Medium) · #214 (three residuals: `R11-02` Low, `R11-10` Low, `R11-12` Low) · #215 (residual `R11-06`, Medium; `+2`/`+3` settled) · #216 (residual `R11-07`, Medium) |
| **superseded/withdrawn/tracking** | #26 (this meta-issue) · #61–#74, #100–#101 (not part of our verified set) · #167, #168, #174, #175 (folded into round-8/9 dispositions) · #193, #195, #197 (fully closed as of round 9/10) · #206 (rule reversed by #212, our pinned test retired as `SUPERSEDED-RULE`, not a regression) |

**We never close or reopen upstream issues ourselves — every "closed" row above reflects our own re-verification; the residual, where one exists, is filed as a new `R{n}-nn` issue rather than a reopen.**

## Round 11 — new findings

| ID | Sev | Title |
|---|---|---|
| `R11-04` | High | `_timer_handles` grows by one retained entry per `raise(delay=)` beat and is never pruned — an unbounded leak on the heartbeat shape #212 just made legal |
| `R11-06` | Medium | #215's `_descent_done` gate: an entry action that awaits its own receipt hangs `start()` forever, silently |
| `R11-07` | Medium | #216 validates the root config only: a misspelled key inside a state is silently dropped, with no raise and no warning, even under `strict_config=True` |
| `R11-08` | Medium | Restore then re-persist without `start()` silently drops every armed delayed self-send — #213's own failure mode, one hop later |
| `R11-09` | Medium | A `RunawayChainError` chain trip reaches only `last_error`, and the next benign event erases it — a permanently inert machine reports healthy |
| `R11-10` | Low | `on_invalid_event` is structurally unreachable on the restore path (raised as a note on #214, not filed separately) |
| `R11-11` | Low | `structure_hash` omits `raise(delay=)` delays although it covers `after` delays (raised as a note on #213) |
| `R11-12` | Low | `lane` is persisted but unenforceable on the sync engine (raised as a note on #214) |

## Our refuted / withdrawn claims

We would rather withdraw a finding loudly than leave a bad one on the record:

- **R11-01 refuted outright, filed as Blocker internally, not filed upstream.** Editing `"version": 3` → `2` mints forged `done`/`error`/`after` records as engine-authentic — the mechanism reproduces exactly — but the control probe kills it: an attacker who can edit `version` can equally edit `state_ids` and land in the target state directly, with no event forgery at all. `from_snapshot` is a documented trusted-input boundary (#205); `machine_hash` is a fingerprint, not a MAC; `from_snapshot(minimum_version=3)` correctly raises `SnapshotVersionError` on the forged blob. Residual: the snapshot guide should recommend `minimum_version=3`, not `1` (`R11-01` note on #214).
- **R11-02 downgraded, High → Low.** `scheduled_sends` skips the `strict` check `pending_events` gets, so a chart upgrade that undeclares an event yields silent delivery instead of refusal — a genuine contract inconsistency, but not a security hole: forging `configuration` alone reaches the same target state with no event at all (`events.py:421`). Fix looks like one line (`_rearm_restored_self_sends` through `_admit_restored`); filed as a note on #214, not a standalone issue.
- **R11-03 refuted outright.** `after`-provenance is forgeable only via non-exported modules, an already-held genuine engine event, or blob-write — and blob-write reaches the target state with no event at all, same reasoning as R11-01. The only vector reachable from the documented public API (V1) is correctly refused with `UnknownEventError`.
- **R11-05 refuted outright.** We briefly held a finding that #212's timer exemption keys on delay *truthiness*, so `raise(delay=0.0001)` escapes `maxIterations`. Plain `after:` at the same delays behaves identically on the same charts and has been exempt since long before #212 — nothing regressed; #212 achieved parity with a path the budget never bounded by design. Also not a liveness failure: an external `send` during the spin is served in ~16 ms, the platform timer floor. The only live observation is that `delay` is milliseconds, so `0.0001` is 100 ns — API misuse, not a defect.

**This is the third round running in which a Blocker filed against engine-event provenance was refuted by our own control probe (R11-01, following R10-01 and an earlier round).** We are adopting the check as a triage precondition, not a refutation step: any finding whose threat model requires blob-write must first be tested against "what does the same writer achieve with `state_ids`/`context` alone?" — see the `did_v3_or_v2_upcast_reopen_the_195_203_forgery_boundary` control-probe reasoning above, answered **No** for the same reason on all three vectors this round.

The `did_212_reopen_a_bounded_cycle_class` question is likewise answered **No**: a purpose-built collateral-unboundedness probe found no previously-bounded shape that became unbounded (watchdogs on both `def` and `async def` lanes), and the one stable PASS→FAIL delta across 163 gate checks and 527 sweep scripts is our own test encoding the #206 rule that #212 deliberately reverses — retired as `SUPERSEDED-RULE`, not reported as a regression. The caveat, honoured in full above, is that #212 made the pre-existing `R11-04` resource defect unbounded.

## Coverage

Standing measurement: **92.78 % at `19cb1f1`** (3505 passed / 13 skipped / 0 failed / 566.57 s), carried forward as the last completed full-suite run. This round's own suite run did not complete in the time budget for the third consecutive round (reached 4 %, 3535 collected, 0 failures observed before the cap) — the coverage figure above is not re-measured at `c78ce99` and will be appended once a completed run is available. Supporting targeted runs at this commit: `test_round10_findings` 15/15, the round 8/9/10 combined suite 65/65 on both hash seeds.

## Release note — before tagging 0.8.1

**We would pin a tag cut at `c78ce99` as-is, with CV-C47 enforced.** CV-C47 (no `raise(delay=)` self-paced periodic work) already bans exactly the shape that leaks in `R11-04`, and was written a round ago for an unrelated finding — we did not have to invent a mitigation under pressure. We recommend fixing `R11-04` first (one line per engine — the `after` path's `owner_id=state.id` pattern already exists four hundred lines away) and then bumping `__version__` to match before tagging 0.8.1; `c78ce99` still reports `0.8.0`, which is why every disposition in this document keys on the commit hash rather than the version string. Nothing else in this round's findings is tag-blocking: the four Mediums (`R11-06` through `R11-09`) and five Lows are each a narrow, documented-scope residual with a stated workaround, not a release blocker.

Thank you for eleven rounds of this. The round-9 ask to parametrise service-invoking tests over `def`/`async def` has now kept the service-kind axis flat across our entire corpus for two consecutive rounds, and this round's fixes — four of five carrying only a scope residual, not a failure of the mechanism that shipped — are the most tractable defect list the series has produced.
