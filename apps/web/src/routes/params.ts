/**
 * Deep-link parameter validators (`docs/plan/12-sitemap.md` §7).
 *
 * Each validator is a pure function returning the corrected value plus
 * whether a correction happened, so the UI can both apply the fallback and
 * explain it (toast) per the ticket's acceptance criteria. Server-side
 * re-validation is assumed for every scope-bearing param (`account`,
 * `symbol`) — these functions are convenience/UX only, never an
 * authorisation grant.
 */

export interface ValidationResult<T> {
  readonly value: T;
  readonly corrected: boolean;
  readonly reason?: string;
}

const BYBIT_SYMBOL_RE = /^[A-Z0-9]{5,20}$/;

export function validateSymbol(
  raw: string | null | undefined,
  lastSymbol: string,
): ValidationResult<string> {
  if (raw && BYBIT_SYMBOL_RE.test(raw)) {
    return { value: raw, corrected: false };
  }
  return {
    value: lastSymbol,
    corrected: true,
    reason: "Unknown symbol; showing your last symbol instead.",
  };
}

export const TIMEFRAMES = [
  "1",
  "3",
  "5",
  "15",
  "30",
  "60",
  "120",
  "240",
  "360",
  "720",
  "D",
  "W",
  "M",
] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
const DEFAULT_TIMEFRAME: Timeframe = "15";

export function validateTimeframe(raw: string | null | undefined): ValidationResult<Timeframe> {
  if (raw && (TIMEFRAMES as readonly string[]).includes(raw)) {
    return { value: raw as Timeframe, corrected: false };
  }
  return {
    value: DEFAULT_TIMEFRAME,
    corrected: true,
    reason: `Invalid timeframe; falling back to ${DEFAULT_TIMEFRAME}.`,
  };
}

export function validatePaneFocus(raw: string | null | undefined): ValidationResult<string | null> {
  if (raw && raw.trim().length > 0) return { value: raw, corrected: false };
  return { value: null, corrected: false };
}

const PANEL_IDS = new Set(["order-ticket"]);

export function validatePanel(raw: string | null | undefined): ValidationResult<string | null> {
  if (!raw) return { value: null, corrected: false };
  if (PANEL_IDS.has(raw)) return { value: raw, corrected: false };
  return { value: null, corrected: true, reason: "Unknown panel; ignoring the param." };
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function validateAccount(raw: string | null | undefined): ValidationResult<string | null> {
  if (!raw) return { value: null, corrected: false };
  if (UUID_RE.test(raw)) return { value: raw, corrected: false };
  return { value: null, corrected: true, reason: "Malformed account id; ignoring the param." };
}

const GROUP_BY = new Set(["symbol", "account", "manager"]);

export function validateGroupBy(raw: string | null | undefined): ValidationResult<string> {
  if (raw && GROUP_BY.has(raw)) return { value: raw, corrected: false };
  return { value: "symbol", corrected: true, reason: "Invalid groupBy; falling back to symbol." };
}

export function validateShowClosed(raw: string | null | undefined): ValidationResult<boolean> {
  if (raw === "true") return { value: true, corrected: false };
  if (raw === "false" || raw === null || raw === undefined) {
    return { value: false, corrected: false };
  }
  return { value: false, corrected: true, reason: "Invalid showClosed; falling back to false." };
}

export function validateIsoDateTime(
  raw: string | null | undefined,
): ValidationResult<string | null> {
  if (!raw) return { value: null, corrected: false };
  const ms = Date.parse(raw);
  if (!Number.isNaN(ms)) return { value: raw, corrected: false };
  return { value: null, corrected: true, reason: "Invalid date; ignoring the param." };
}

const MIN_SPEED = 0.5;
const MAX_SPEED = 100;
const DEFAULT_SPEED = 1;

export function validateSpeed(raw: string | null | undefined): ValidationResult<number> {
  const parsed = raw === null || raw === undefined ? NaN : Number(raw);
  if (Number.isNaN(parsed)) {
    return { value: DEFAULT_SPEED, corrected: true, reason: "Invalid speed; falling back to 1x." };
  }
  const clamped = Math.min(MAX_SPEED, Math.max(MIN_SPEED, parsed));
  if (clamped !== parsed) {
    return { value: clamped, corrected: true, reason: `Speed clamped to ${clamped}x.` };
  }
  return { value: clamped, corrected: false };
}

export function validateFromReplay(
  raw: string | null | undefined,
): ValidationResult<string | null> {
  if (raw && raw.trim().length > 0) return { value: raw, corrected: false };
  return { value: null, corrected: false };
}

const RULE_MODES = new Set(["form", "graph"]);

export function validateRuleMode(
  raw: string | null | undefined,
): ValidationResult<"form" | "graph"> {
  if (raw && RULE_MODES.has(raw)) return { value: raw as "form" | "graph", corrected: false };
  return { value: "form", corrected: true, reason: "Invalid mode; falling back to form." };
}

export function validateStandalone(raw: string | null | undefined): ValidationResult<boolean> {
  if (raw === "1" || raw === "true") return { value: true, corrected: false };
  return { value: false, corrected: false };
}
