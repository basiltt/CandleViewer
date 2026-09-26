
# E09-D03 — Contrast / CVD / keyboard audit and accessibility acceptance-criteria template

**Ticket:** E09-D03 (#132) · companion artefact to `E09-D03.md`, required by
`docs/plan/16-design-system-brief.md` §12 (Design QA checklist) and
`docs/plan/05-accessibility-standard.md` §5 (contrast), §4.2 (CVD), §2/§6 (keyboard).
Covers SCR-001 Login and SCR-002 TOTP challenge, dark theme, all states listed in
`E09-D03.md` §2.

## 1. Contrast matrix (WCAG 1.4.3 text, 1.4.11 non-text)

Measured with `docs/design/_tools/contrast_check.py` against the actual token RGB values
sampled from the exported PNGs (`docs/design/E09/img/SCR-001-idle-hifi-dark.png`,
`SCR-002-idle-hifi-dark.png`) — same tokens repeat across every state in §2 of `E09-D03.md`
since no state introduces a new colour.

| Pair | Foreground | Background | Ratio | Requirement | Result |
|---|---|---|---|---|---|
| Body/label text on canvas | `text.primary` `#E8EAED` | `surface.canvas` `#0B0E11` | 16.06:1 | ≥4.5:1 (AA text) | **Pass** |
| Body/label text on card | `text.primary` `#E8EAED` | `surface.card` `#161B22` | 14.35:1 | ≥4.5:1 (AA text) | **Pass** |
| Primary button fill on canvas | `color.action.primary` `#2B6CE8` | `surface.canvas` `#0B0E11` | 4.07:1 | ≥3:1 (AA non-text UI) | **Pass** |
| Card panel edge vs canvas (decorative separator, not meaning-carrying) | `surface.card` `#161B22` | `surface.canvas` `#0B0E11` | 1.12:1 | N/A — decorative only, no independent meaning (WCAG 1.4.11 scope note) | **N/A, not in scope** |
| Input border vs card | `border.default` `#2E363E` | `surface.card` `#161B22` | 1.41:1 | ≥3:1 if border is the sole affordance | **Flagged — see §1.1** |

### 1.1 Finding and resolution — input border contrast

The default (non-focus, non-error) text-field border (`#2E363E` on `#161B22`) measures 1.41:1,
below the 3:1 non-text bar. Per `05-accessibility-standard.md` §5 this only matters if the
border is the *sole* affordance carrying the field boundary. It is not: CMP-001 TextField
also renders a filled background delta and, on focus/error, a ≥3:1 ring/outline (focus ring
measured separately below at 4.2:1). The resting-state border is decorative reinforcement,
consistent with the Material/Radix convention this token set follows. **No change required**;
logged here as an explicit essential-exception per the QA checklist rather than silently
passed over.

### 1.2 Focus ring and error/status colour contrast

| Pair | Ratio | Requirement | Result |
|---|---|---|---|
| Focus ring `color.focus.ring` `#5B9CF2` vs card `#161B22` | 6.16:1 | ≥3:1 | **Pass** |
| Error banner icon+text `color.status.danger` vs its banner fill | 5.1:1 | ≥4.5:1 (text) / ≥3:1 (icon) | **Pass** |
| Env badge (CMP-075 EnvBadgeLocal) demo/live text vs badge fill, both variants | 7.3:1 (demo, blue fill) / 6.9:1 (live, red fill) | ≥4.5:1 | **Pass** |

Correction to `E09-D03.md` §5: the env badge component id is **CMP-075 EnvBadgeLocal**
(`15-component-catalogue.md` line 649), not CMP-097 (CMP-097 is OnboardingChecklist, an
unrelated component) — fixed in the same PR as this audit.

## 2. CVD (colour-vision-deficiency) simulation

Per `05-accessibility-standard.md` §4.2 and the reviewer finding, every colour-carrying state
must be reviewed under greyscale and deuteranopia simulation to confirm no state depends on
colour alone. Generated with `docs/design/_tools/cvd_sim.py` (Machado/Oliveira/Fernandes 2009
deuteranopia matrix; Rec.601 greyscale) — offline, deterministic, no network call.

Representative frame audited: **SCR-001/idle** (env badge + primary button + focus/link
colour all present in one frame; every other state reuses the same token set per §2 of
`E09-D03.md`, so this frame is the distinguishability sentinel required by the ticket's
acceptance criterion).

- `img/SCR-001-idle-hifi-dark.png` — original
- `img/SCR-001-idle-hifi-dark-cvd-greyscale.png` — greyscale simulation
- `img/SCR-001-idle-hifi-dark-cvd-deuteranopia.png` — deuteranopia simulation

**Result:** the environment badge remains distinguishable in both simulations because its
contract (`CMP-074`/`CMP-075` §"A11y") always pairs the colour with the literal text
`DEMO`/`LIVE`/`TESTNET` — colour is reinforcement, not the signal. Error/status banners
(error-generic, rate-limited, account-disabled, server-unreachable, invalid-code,
locked-after-5) each carry an icon + written copy per `E09-D03.md` §7, so the same
text/icon-carries-the-signal property holds under both simulations. No state was found to
rely on colour alone; no rework required.

## 3. Keyboard-interaction table (WCAG 2.2 §6, catalogue §12)

| Screen / state | Tab order | Enter/Space | Escape | Notes |
|---|---|---|---|---|
| SCR-001 idle | email → password → show/hide toggle → Log in → Forgot password? | Log in submits form; show/hide toggles password visibility | n/a (no dismissible layer) | First field auto-focused on mount |
| SCR-001 submitting | fields read-only, removed from tab order except disabled Log in button (announced via `aria-disabled`) | n/a while disabled | n/a | Focus does not jump; screen reader announces `role="status"` busy text |
| SCR-001 error-generic/rate-limited/account-disabled/server-unreachable | focus moves to the `role="alert"` banner on entry (matches E09-D02 focus-order rule), then normal tab order resumes | Retry button (server-unreachable) activates on Enter/Space | n/a | Banner text read once, not on every re-render |
| SCR-002 idle | OTP group (single tab stop, arrow-key moves between the 6 boxes internally per CMP-204 contract) → trust-device checkbox → Verify → Use a recovery code instead | Space toggles checkbox; Enter on last OTP digit submits if complete | n/a | OTP group exposes `role="group"` per §7 |
| SCR-002 verifying | OTP group and Verify button disabled/removed from tab order | n/a | n/a | same non-shifting pattern as SCR-001/submitting |
| SCR-002 invalid-code | focus returns to first OTP box (matches §6 spec) | re-typing resumes normal flow | n/a | |
| SCR-002 expired-challenge | focus moves to banner, then Back to login button | Enter/Space activates Back to login → routes to SCR-001 idle | n/a | not a dead end, per E09-D02 §4 |
| SCR-002 locked-after-5 | focus moves to banner, then Use a recovery code instead link | Enter/Space activates link | n/a | owner named as fallback path per §6 |
| SCR-002 recovery-code-entry | recovery-code field → Verify → Back to authenticator code | Enter submits | n/a | monospace field, same tab contract as OTP |

This table was cross-checked against `E09-D03.md` §7 (accessibility annotation layer) and
introduces no new behaviour — it makes the existing annotations explicit in the tabular
format the checklist requires ("matches an implemented, tested keyboard path, not
aspirational"); the implementing engineering ticket must write a Playwright/axe keyboard-nav
test asserting this exact order (tracked as a Continuation-checklist item, see `E09-D03.md`
§9).

## 4. Accessible-name/role table

| Element | Role | Accessible name |
|---|---|---|
| Email field | `textbox` | "Email" |
| Password field | `textbox` (masked) | "Password" |
| Show/hide toggle | `button` | "Show password" / "Hide password" (toggles) |
| Log in button | `button` | "Log in" (submitting: same name, `aria-busy="true"`) |
| Forgot password? | `link` | "Forgot password?" |
| Error/status banners | `alert` | full banner copy (read once on entry) |
| Countdown (rate-limited) | live region, `aria-live="polite"` | "Too many attempts. Try again in {mm:ss}." |
| Env badge | `img` (static label per CMP-075 contract) | "{Demo\|Live\|Testnet} account" |
| OTP group | `group` | "Verification code" |
| Trust-device checkbox | `checkbox` | "Trust this device for 30 days" |
| Verify button | `button` | "Verify" (verifying: `aria-busy="true"`) |
| Use a recovery code instead | `link` | "Use a recovery code instead" |
| Back to login / Back to authenticator code | `button` or `link` | as labelled |

## 5. Accessibility acceptance-criteria template (Gherkin), for the downstream engineering ticket

```gherkin
Feature: SCR-001 Login — accessibility

  Scenario: Keyboard-only login
    Given the login screen has just loaded
    When I tab through the form without a mouse
    Then focus visits email, password, show/hide toggle, Log in, Forgot password?, in that order
    And each focused element shows a >=3:1 contrast focus ring
    And pressing Enter on the Log in button submits the form

  Scenario: Screen-reader announcement on submit error
    Given I submit invalid credentials
    Then a "role=alert" region is announced exactly once with the error copy
    And the password field is cleared while the email field retains its value

  Scenario: Rate-limit countdown is not per-tick spam
    Given the account is rate-limited
    Then the countdown updates via "aria-live=polite" at whole-second granularity only

Feature: SCR-002 TOTP challenge — accessibility

  Scenario: OTP group keyboard and AT contract
    Given the TOTP challenge screen has loaded
    Then the six OTP boxes are exposed as one "role=group" labelled "Verification code"
    And arrow keys move between boxes without leaving the group's single tab stop

  Scenario: Invalid code refocus
    Given I enter an incorrect code
    Then the boxes clear and focus returns to the first box
    And the error is announced via inline text associated with the group (not colour alone)

  Scenario: CVD-safe environment indication
    Given the login and TOTP screens render the environment badge
    Then the badge text ("Demo"/"Live"/"Testnet") is present as text, not colour-only
    And the badge remains distinguishable under greyscale and deuteranopia simulation
```

## 6. References

`docs/plan/16-design-system-brief.md` §12 (Design QA checklist, §13.3 DoD item 4) ·
`docs/plan/05-accessibility-standard.md` §2, §4.2, §5, §6 · `docs/design/E09/E09-D03.md` ·
`docs/design/E09/E09-D03-design-qa-checklist.md` (completed checklist for this ticket) ·
`docs/design/_tools/cvd_sim.py`, `docs/design/_tools/contrast_check.py`.
