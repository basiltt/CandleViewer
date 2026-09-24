# -*- coding: utf-8 -*-
import json, io

T = []

def t(**kw):
    for k in ["key","kind","title","labels","component","phase","sprint","priority",
              "perspective","risk","estimate","parent","blocked_by","milestone","body"]:
        assert k in kw, (kw.get("key"), k)
    assert len(kw["title"]) <= 80, kw["title"]
    T.append(kw)

MS = "R3 Trading on demo"
PH = "P3 Drawing & Alerts"
AREA = "area/paper-trading"

def body(ctx, scope, oos, ac, tech, test, sec, a11y, perf, obs, dod, deps, branch, refs):
    return f"""## Context
{ctx}

## Scope / Deliverables
{scope}

## Out of scope
{oos}

## Acceptance criteria
{ac}

## Technical notes / design
{tech}

## Test plan
{test}

## Security notes
{sec}

## Accessibility notes
{a11y}

## Performance notes
{perf}

## Observability
{obs}

## Definition of Done
{dod}

## Dependencies
{deps}

## Branch
{branch}

## References
{refs}
"""

DOD_COMMON = """- [ ] Acceptance criteria demonstrated by automated tests referencing each scenario by name.
- [ ] Coverage: >=85% lines on touched backend/engine packages, >=80% on touched frontend packages; CI coverage gate green.
- [ ] Docs updated: `docs/plan/22-api-openapi.yaml`, `docs/plan/23-ws-protocol.md`, `docs/plan/24-internal-schemas.md`, `docs/plan/21-database-schema.md` reflect shipped behaviour where they diverged.
- [ ] Changelog fragment added per `docs/plan/07-release-and-prr.md` §3.
- [ ] 2 approvals incl. 1 code-owner; PR <=400 LOC diff; merged via merge queue.
- [ ] QA sign-off comment posted with pass/fail per scenario (`docs/plan/02-definition-of-ready-done.md` §3.2).
- [ ] Feature-flag state recorded (which flag gates this, default per environment)."""

DOD_UI = DOD_COMMON + """
- [ ] Design sign-off: built screen compared against the Figma spec by a designer (`design-qa`); discrepancies fixed or filed as Bug with priority.
- [ ] a11y: axe-core CI green on the touched screens, manual screen-reader pass recorded, keyboard-only path verified (`docs/plan/05-accessibility-standard.md`).
- [ ] Storybook stories added/updated for every touched component with all states.
- [ ] Demoed at Sprint Review against staging (demo)."""

DOD_DESIGN = """- [ ] Artefact complete in Figma at the stated fidelity, linked on the ticket.
- [ ] Every state from `docs/plan/14-screens-catalogue.md` drawn (default, loading, empty, error, not-permitted, transitional).
- [ ] The screen's "Design sign-off acceptance checklist" in `docs/plan/14-screens-catalogue.md` is fully ticked.
- [ ] Tokens used are design-system tokens from `docs/plan/16-design-system-brief.md`; any new token/component raised as a design-system contribution ticket, never a one-off.
- [ ] Reviewed and signed off by the Chief Design Officer (or delegate) and the Architect; sign-off comment recorded on the ticket.
- [ ] a11y annotations present: focus order, accessible names, live-region behaviour, colour-independent encoding.
- [ ] Handed to engineering >=2 sprints before the consuming FE story's sprint (design-ahead rule, `docs/plan/00-planning-brief.md` §Team & cadence)."""

DOD_QA = """- [ ] Test artefacts committed under `qa/` (plans) or `tests/e2e`/`tests/load`/`tests/chaos` (code) and wired into CI where automated.
- [ ] Every scenario has an explicit pass/fail result recorded on the ticket.
- [ ] Defects raised as Bug tickets with repro steps, severity and the failing scenario id linked.
- [ ] Fixtures used are named and reproducible (recorded Bybit fixture ids or the `CV_FEED=synthetic` generator).
- [ ] Sign-off comment posted by QA/SDET; deviations ("QA capacity deviation") stated explicitly if any.
- [ ] Coverage/quality gates for the epic re-checked after execution."""

DOD_SEC = """- [ ] Findings recorded in the epic's STRIDE worksheet under `docs/security/threat-models/E38-paper-trading.md`.
- [ ] Every Critical/High finding fixed or accepted-risk with Owner sign-off recorded (`docs/plan/04-security-program.md`).
- [ ] SAST (Semgrep/Bandit/CodeQL), SCA (pip-audit/npm audit) and secrets scan clean or triaged on the touched paths.
- [ ] Security engineer review comment present on the ticket.
- [ ] Any new detection rule committed to the Semgrep/ZAP rule set and running in CI.
- [ ] `docs/plan/32-risk-register.md` updated if the review surfaced or retired a risk."""
