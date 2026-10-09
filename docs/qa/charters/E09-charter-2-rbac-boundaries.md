# E09-C2 Charter: RBAC boundary probing

- Ticket: E09-Q06 (#297) · Format: session-based test management · Date: 2026-10-09
- Tester: AI agent (Agent B). **Deviation (honest scope):** no staging build, no browser session recording, no 60-120 min human time box, and no docker stack were available. Each session was an in-process exploration: the listed oracles were checked against the existing fakes-backed suites by re-running them, plus a code-read of the services. Nothing here was observed in a real browser. Items needing a human or staging are listed under "Not probed" with the open issue that owns them.
- No credentials used; fixtures are deterministic and fake.
- Cross-post: Security co-review of this debrief is requested (E09-X02 / #298 owns abuse cases; not duplicated here).

## Charter
As a viewer and a grantless manager, try every admin/owner affordance by deep link, replay, role downgrade and cross-account WS subscription.

## Oracles
- O1 Any screen or route reachable that the role's permission set does not include.
- O2 Any denial that differs between "exists but forbidden" and "does not exist" for other accounts (enumeration).
- O3 Any denial with no audit row.
- O4 Any live socket keeping a topic after its grant is withdrawn.

## Areas covered (in-process evidence)
| Probe | Evidence | Result |
|---|---|---|
| Every route x five actors | `tests/contract/rbac/test_route_matrix.py` (9 tests, matrix-driven) | matrix matches app |
| Capability but non-granted account | `test_scope_and_ws.py::test_valid_capability_but_non_granted_account_is_403_nothing_mutated_and_audited` | 403, audited (O3 ok) |
| Grantless manager cannot create | `test_manager_without_any_grant_cannot_create_even_with_the_capability` | refused |
| Admin mutations owner-only and step-up gated | `test_administrative_mutations_are_owner_only`, `..._require_step_up_even_for_the_owner` | ok |
| Self-service with a target user id (IDOR) | `test_self_service_routes_reject_a_target_user_id_in_the_body` | rejected |
| WS topic x actor, non-entitled gets error not silent empty | `test_every_topic_family_x_actor_matches_the_matrix`, `test_non_entitled_role_gets_forbidden_not_a_silent_empty_subscription` | ok |
| In-flight subscription after grant withdrawn / downgrade | `test_in_flight_subscription_gets_revoked_when_the_grant_is_withdrawn`; `tests/unit/test_ws_permissions.py::test_downgrade_pushes_frame_revokes_and_refuses_orders` | revoked (O4 ok) |
| Role change over WS e2e | `tests/unit/ws/test_gateway_e2e.py::test_ws_e2e_permissions_sub_check_and_live_role_change` | ok |
| Browser deep link as viewer | `apps/web/e2e/auth/denied.spec.ts` (E09-TC-E06/E07, network-stubbed) | uniform denied page |

Run result: 404 tests passed (contract/rbac, authz abuse, ws permissions, gateway e2e, deny-by-default).

## Not probed
- Browser back/forward after a role downgrade (needs a real browser against a backend; stub-level only).
- Replaying a captured request against a live server (E2E backend lane needs the E03 ephemeral stack; see `qa/plans/e09-q02-automation-status.md`).
- Rules-manager grant isolation (SR-050 layer 2): #2094. Owner check shape in rules_actor: #2096.
- CSRF token negative test: blocked by #2090.

## Anomalies
None observed in-process. Known open items above are already tracked.
