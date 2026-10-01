// E17-T05: single client-side error-mapping table (23-ws-protocol.md 10.3).
// Driven by the generated registry metadata (@candleviewer/protocol); the UI class of a
// code is looked up here and nowhere else, so a transient `degraded_data` can never be
// rendered as a focus-stealing modal.
import { ERROR_META, type ErrorCode } from "@candleviewer/protocol";

export type ErrorUiClass = "fatal" | "transient" | "clientBug" | "capacity";

export interface ErrorTreatment {
  readonly uiClass: ErrorUiClass;
  /** Fatal: blocking modal and route to login / an explanatory screen. */
  readonly modal: boolean;
  /** Transient: inline staleness badge + connection chip. */
  readonly inlineBadge: boolean;
  /** Client bug: console error + report-a-bug toast (never silently swallowed). */
  readonly consoleError: boolean;
  readonly toast: "none" | "reportBug" | "fewerPanes";
  /** Capacity: auto-reduce throttles. */
  readonly autoReduceThrottle: boolean;
  readonly retryable: boolean;
}

const FATAL: readonly ErrorCode[] = ["auth_failed", "forbidden", "user_disabled"];
const TRANSIENT: readonly ErrorCode[] = ["degraded_data", "exchange_unavailable", "token_expired"];
const CLIENT_BUG: readonly ErrorCode[] = [
  "protocol_violation",
  "frame_malformed",
  "invalid_options",
];
const CAPACITY: readonly ErrorCode[] = [
  "slow_consumer",
  "subscription_limit",
  "client_rate_limited",
];

const CLASS_OF = new Map<ErrorCode, ErrorUiClass>([
  ...FATAL.map((c): [ErrorCode, ErrorUiClass] => [c, "fatal"]),
  ...TRANSIENT.map((c): [ErrorCode, ErrorUiClass] => [c, "transient"]),
  ...CLIENT_BUG.map((c): [ErrorCode, ErrorUiClass] => [c, "clientBug"]),
  ...CAPACITY.map((c): [ErrorCode, ErrorUiClass] => [c, "capacity"]),
]);

function treatmentFor(uiClass: ErrorUiClass, retryable: boolean): ErrorTreatment {
  return {
    uiClass,
    modal: uiClass === "fatal",
    inlineBadge: uiClass === "transient",
    consoleError: uiClass === "clientBug",
    toast: uiClass === "clientBug" ? "reportBug" : uiClass === "capacity" ? "fewerPanes" : "none",
    autoReduceThrottle: uiClass === "capacity",
    retryable,
  };
}

/**
 * Treatment for a wire error code. A code the section 10.3 table does not classify (or one
 * outside the registry) is treated as a client bug, never silently swallowed.
 */
export function classifyError(code: string): ErrorTreatment {
  const meta = (ERROR_META as Readonly<Record<string, { retryable: boolean } | undefined>>)[code];
  const uiClass = CLASS_OF.get(code as ErrorCode) ?? "clientBug";
  return treatmentFor(uiClass, meta?.retryable ?? false);
}
