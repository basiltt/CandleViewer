# Comment draft — note on #220: the recursion does not descend into an inline-machine `invoke.src`

**NOT POSTED. Draft.** Severity on our board: **Low**. Against `main` @ `de2da4e`.

Posting as a note on the #220 thread rather than a new issue, because it is a scope boundary of the fix that just landed rather than an independent defect, and because #220 is otherwise the most complete key check we have measured (638/640 injected typos caught at up to 11 nesting levels, 0 false positives on 400 valid charts).

## The gap

The recursion covers nested `states`, parallel regions, `on` / `always` / `after` / `onDone` transition bodies, `invoke` entries and their `onDone` / `onError`. It does **not** descend into a machine definition supplied **inline** as `invoke.src` — that sub-config is not re-entered with `KNOWN_ROOT_KEYS` / `KNOWN_STATE_KEYS` the way a top-level config is.

The practical effect is that a typo inside an inline invoked machine is silently dropped under every strict setting, which is the same failure mode #220 was written to close, one composition level further in.

## Why it is Low, and also why it is worth doing

Low because an inline invoked machine is the less common spelling — most invoked machines are passed as an already-built `MachineNode` or a factory, and those are validated when *they* are created. We have no chart that uses the inline form today.

Worth doing because an inline sub-machine is precisely the place where a typo is least likely to be caught by eye: it is nested inside a state, inside an `invoke`, in a region of the config that reviewers tend to skim as "the child's business". The fix is presumably a recursive call at the `invoke.src`-is-a-dict branch, reusing the machinery already written.

## Consequence on our side

We have a wrapper-level recursive key check of our own, written when the check was root-only. #220 now covers everything it covered **except** this, so rather than retiring it we have re-grounded it on exactly this hole. If the recursion picks up inline `invoke.src`, our check retires entirely — which is the outcome we would prefer, and we mention it so the value of closing a Low is visible: it removes a whole duplicated validator from a downstream project.
