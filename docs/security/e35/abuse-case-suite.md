# E35 abuse-case suite, SAST rules and DAST plan (E35-X02)

Continuous-enforcement half of the E35 security posture (analysis: E35-X01, review: E35-X03).
Threat model: [`../threat-models/e35-rule-engine.md`](../threat-models/e35-rule-engine.md).

## Semgrep rules (`.semgrep/`, fixtures in `.semgrep/tests/`, run by `tools/ci/check_semgrep_rule_tests.py`)

| Rule | Enforces |
|---|---|
| `cv-rules-no-dynamic-eval` | ADR-0007 R1: no `eval/exec/compile/__import__/pickle.load(s)` in `rules/` |
| `cv-rules-no-exchange-import` | rule engine never imports `candleviewer.exchange*`; actions go via OMS |
| `cv-rules-no-sensitive-log` | no `input_snapshot`/balance/equity args to log calls at INFO or below |
| `cv-rules-no-order-payload` | no exchange order payload dict literals (`orderType`, `orderLinkId`, `stopLoss`, `reduceOnly`) so the OMS native-SL path cannot be bypassed |
| `cv-rules-no-scope-check-outside-resolver` | heuristic: no ad-hoc `in/not in ...granted_accounts` in evaluator/runner/service; use `ScopeResolver` |

Each ships a positive (`# ruleid:`) and negative (`# ok:`) fixture, and is verified to be clean on the current tree.

## Abuse-case suite (`services/api/tests/rules/abuse/`, ordinary pytest, merge-queue suite)

| Case | Test | Status |
|---|---|---|
| a ungranted account | `test_ac_a_*` | enforced (403 + `rule_scope_denied` audit, no state change) |
| b no simulation on current hash | `test_ac_b_*` | enforced (422 `simulation_required`, `rule.mode_refused` audit) |
| c open safety warning | `test_ac_c_*` | enforced (422 `safety_warning_open`) |
| d live without perm / fresh step-up | `test_ac_d_*` | enforced (403 `permission_required` / `step_up_required`) |
| e loosen stop without `rules.loosen_stop` | `test_ac_e_*` | enforced at save (422) |
| f `all_accounts` without widest grant | `test_ac_f_*` | **strict xfail: control not built** (finding below) |
| g act after post-arming revocation | `test_ac_g_*` | enforced (action denied, `rule_action_scope_denied`/`grant_revoked`) |
| h kill-switch / frozen author | `test_ac_h_*` | enforced (denied + audit `manager_frozen`) |
| i disable `sys.*` built-ins | `test_ac_i_*` | **strict xfail: built-ins not in repo** |
| j/k export / import hygiene | `test_ac_j_k_*` | **strict xfail: endpoints not built** |
| l schema bounds + expensive IR | `test_ac_l_*` | enforced (bounds 422; timeout aborts; auto-disable) |
| m signal loop | `test_ac_m_*` | enforced at save (`feedback_loop`); runtime chain-depth limit not built |
| n read another user's rules | `test_ac_n_*` | enforced (404, no existence leak, no mutation) |

Strict xfail means the test turns red the day the feature lands, forcing the real assertion to be completed.
`test_rbac_matrix.py` asserts every `/rules*` write/read operation x role (anonymous, no perms, reader, writer).

## Findings (triage)

| ID | Severity | Disposition |
|---|---|---|
| X02-F1 `targets: all_accounts` has no widest-grant check | High | deferred: file against the owning engineering ticket; test strict-xfail until fixed |
| X02-F2 `sys.native_sl_watchdog` / `sys.clock_drift_block` do not exist yet | Medium | deferred to the system-rule ticket; DB-level tamper detection to be asserted then |
| X02-F3 export/import not implemented | Medium | deferred (E35-S06); cases j/k xfail |
| X02-F4 runtime emit_signal chain-depth limit absent (only save-time loop rejection) | Medium | deferred |
| X02-F5 pre_trade_check p95 under pathological rule (300 ms) needs integration harness | Medium | shared with E35-Q04; not run locally (no docker) |

## DAST

`.zap/rules-low-priv.yaml`: OpenAPI-driven active scan of `/rules*` with a low-privilege (`rules:read`) bearer
token taken from `ZAP_LOWPRIV_TOKEN`. Any response returning data outside the session's grants is a High finding.
Not run locally (no ZAP/docker); to run in the demo-stack nightly.
