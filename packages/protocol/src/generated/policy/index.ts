// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`.
// Source: tools/gen/export_instrument_policy_rules.py, itself mirroring
// services/api/candleviewer/exchange/policy.py verbatim. Hand edits are
// rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// `linguist-generated` in .gitattributes.
// ==========================================================================
/* eslint-disable */

/** Mirrors `FilterViolationCode` in services/api/candleviewer/exchange/policy.py. */
export type FilterViolationCode =
  | "PRICE_NOT_TICK_MULTIPLE"
  | "QTY_NOT_LOT_MULTIPLE"
  | "QTY_BELOW_MIN"
  | "QTY_ABOVE_MAX"
  | "NOTIONAL_BELOW_MIN"
  | "SYMBOL_NOT_TRADING";

export const FILTER_VIOLATION_CODES: readonly FilterViolationCode[] = [
  "PRICE_NOT_TICK_MULTIPLE",
  "QTY_NOT_LOT_MULTIPLE",
  "QTY_BELOW_MIN",
  "QTY_ABOVE_MAX",
  "NOTIONAL_BELOW_MIN",
  "SYMBOL_NOT_TRADING",
];

/** Mirrors `PriceRoundMode`. Ticket scope: only "nearest" is implemented. */
export type PriceRoundMode = "nearest";

/** Mirrors `QtyRoundMode`. Ticket scope: only "down" (floor) is implemented. */
export type QtyRoundMode = "down";
