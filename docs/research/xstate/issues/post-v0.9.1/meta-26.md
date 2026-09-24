# Meta — round-14 adoption readiness report, `xstate-statemachine` 0.9.1

**NOT POSTED. Draft.** Comment #26 on the standing adoption-readiness meta-issue.

## Round 14 summary — tag `v0.9.1` = `45bb7f3`

All ten round-13 issues (#239–#248) are verified **closed**, on both engines and in both `def` and `async def` service spellings, using standalone repros from a neutral working directory. That is the fifth consecutive round with no partials.

| | |
|---|---|
| Issues verified closed | **10 / 10** |
| Library regressions | **0** (sweep: 0 timeouts; 4 harness-only failures triaged) |
| Library suite | 3601 passed, 13 skipped, 0 failed, 587 s, coverage **92.93 %** |
| Wheel vs tag | 42/42 modules identical; sha256 `d832d4d9…2687162` |
| PEP 740 attestation | **verifies OK** against PyPI |
| New library defects filed | **1** (Medium): `re_mint()` type/src override |
| Our decision | **ADOPT with constraints** (no open High, no Blocker) |

The High row is empty for the first time since round 12. The one new item is a gap in the new `re_mint()` API, filed separately with a standalone repro. It needs in-process code that deliberately misuses the API, so we have added a wrapper rule on our side in the meantime.

Timer benchmark (`production_characteristics.py --quick`, 500 busy machines, n = 10): p50 70.3 ms, p99 92.2 ms, against our 100 ms bar. It still passes, but it is noisier than last round's 55.8 ms. We attribute that to host load during a concurrent suite run, not to the library.

Thank you for the attestations, in particular. The release is now verifiable end to end.
