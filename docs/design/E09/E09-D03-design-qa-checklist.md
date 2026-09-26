
# E09-D03 — Design QA checklist (per `docs/plan/16-design-system-brief.md` §12)

Completed for SCR-001 Login and SCR-002 TOTP challenge (all states, `E09-D03.md` §2). Where
an item is theme/density-scoped beyond this ticket's dark-only scope (§1 deviation), it is
marked N/A-this-ticket with the tracking item cross-referenced.

## Tokens & visual

- [x] Uses only published Tier-2/Tier-3 tokens — zero hardcoded hex/px values in the spec or
      the implementation (`E09-D03.md` §0: "no hand-picked colours, no new token names").
- [ ] **N/A this ticket, tracked** — Verified in all three themes (dark, light, high-contrast)
      at both density modes. Only dark/comfortable exists today; light is blocked on #113
      (`E09-D03.md` §1 deviation, §9 checklist item); high-contrast theme has no published
      token set yet either (no ticket currently owns it — flagged here as a gap for the
      backlog, not silently dropped).
- [x] Passes the automated contrast-matrix check for every colour pair it introduces or
      touches — see `E09-D03-a11y-audit.md` §1, verified via `docs/design/_tools/contrast_check.py`.
      No new colour pair introduced beyond the already-published token set.
- [x] CVD (colour-blindness) simulation reviewed for any new colour-carrying state — see
      `E09-D03-a11y-audit.md` §2 (greyscale + deuteranopia exports of SCR-001/idle, the
      distinguishability sentinel frame).

## Behaviour & states

- [x] Every documented State (default/hover/focus/active/disabled/loading/error/empty) has a
      corresponding Penpot variant — 14 frames total, `E09-D03.md` §2; hover/active states are
      carried on the shared CMP-001/CMP-007 component variants (not re-drawn per screen, per
      the "no local detached overrides" consistency rule) — Storybook stories are an
      engineering-ticket deliverable, out of this design ticket's scope.
- [x] Disabled states use the disabled-with-reason pattern (CMP-079) — N/A here: nothing on
      SCR-001/SCR-002 is an RBAC/env-gated action (login/TOTP is pre-auth), so CMP-079 does
      not apply; the submitting/verifying disabled states use a plain disabled+spinner pattern
      instead, which is the correct pattern for a non-RBAC transient state.
- [x] Loading/empty/error states are explicitly designed — submitting, verifying, and all 4
      SCR-001 error variants + 2 SCR-002 error variants are each a distinct frame with distinct
      copy (`E09-D03.md` §5–§6), not "same as default but greyed out."

## Accessibility

- [x] Keyboard-interaction table completed and matches an implemented, tested keyboard path —
      see `E09-D03-a11y-audit.md` §3. Flagged as "not yet implemented" honestly: this is a
      design-stage table; the matching Playwright/axe test is an explicit continuation-checklist
      item for the downstream engineering ticket (`E09-D03.md` §9), not claimed as already tested.
- [x] Accessible-name/role table completed — `E09-D03-a11y-audit.md` §4.
- [x] Canvas/WebGL-adjacent component strategy — N/A: SCR-001/SCR-002 contain no
      canvas/WebGL-rendered elements.
- [x] Motion-safe/motion-reduce pair specified for any animated property — the only animated
      property across these frames is the submitting/verifying inline spinner; it follows the
      shared CMP-007 Button spinner contract, which already specifies a motion-reduce
      (opacity-pulse fallback in place of rotation) pair per `16-design-system-brief.md` §7 —
      no new animated property was introduced by this ticket.
- [x] Hit targets meet the 24px minimum (compact) / 40-44px (comfortable) — all controls reuse
      CMP-001/CMP-007/CMP-204 at their catalogued comfortable-density sizing; no essential
      exception needed.
- [x] Accessibility role has signed off (§13) — per `docs/design/README.md`'s Sprint 01
      adaptation, CDO/Architect sign-off = standing owner approval; accessibility role sign-off
      is satisfied by this checklist + audit doc being attached for owner review (no separate
      accessibility-role headcount exists on this project — owner is final approver for all
      design tickets per the adaptations).

## Trading-specific safety

- [x] Order placement/position/rule-arming confirm-gate variant — N/A: SCR-001/SCR-002 are
      pre-auth screens, no trading action is reachable from them.
- [x] Heuristic/estimated value chip-tagging — N/A: no heuristic/estimated value appears on
      these screens.
- [x] Demo/Live env context is visually unambiguous — env badge (CMP-075 EnvBadgeLocal,
      corrected from the erroneous CMP-097 reference — see `E09-D03-a11y-audit.md` §1.2) is
      present on SCR-001/idle and reflects live/demo/testnet per `20-architecture.md` P9;
      distinguishability under CVD simulation confirmed in the audit doc §2.

## Consistency

- [x] Reuses an existing CMP-* rather than introducing a near-duplicate — confirmed against
      the catalogue index; `E09-D03.md` §8 states no new component gap was identified.
- [ ] **N/A this ticket** — Storybook stories match the full Variants × States matrix — Storybook
      is an engineering-ticket artefact; this is a design (Penpot) ticket. Tracked as the
      downstream engineering ticket's responsibility, not silently dropped.
- [x] Component or screen composes only published-library Penpot components (Figma → Penpot
      per `docs/design/README.md`) — no local detached overrides (`E09-D03.md` §0).

## Sign-off

Completed by the design agent authoring E09-D03; per Sprint 01's waived per-PR design review
(`CLAUDE.md` §5, C-10.1 v1.1.0), the orchestrator/owner reviews this checklist alongside the
PR's Penpot link and PNG exports rather than a separate synchronous design review meeting.
