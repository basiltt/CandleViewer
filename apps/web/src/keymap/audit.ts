import { getCommand } from "./keymap";

export const TRADING_BINDING_CHANGED = "hotkey.trading_binding_changed";

export interface AuditRecord {
  readonly action: typeof TRADING_BINDING_CHANGED;
  readonly commandId: string;
  readonly before: string;
  readonly after: string;
  readonly acknowledgedUnsafe: boolean;
}
export type AuditSink = (r: AuditRecord) => void;

/**
 * Single choke point for rebinding audit (CMP-093 AuditActionTrigger contract): every binding
 * change goes through `applyRebind`, which emits for destructive (trading) commands, so no
 * caller can change one without the audit event. The sink is injected by the shell; the default
 * dispatches a DOM event the shell's audit transport listens to.
 */
let sink: AuditSink = (r) => window.dispatchEvent(new CustomEvent("cv:audit", { detail: r }));
export function setAuditSink(s: AuditSink): void {
  sink = s;
}

export function applyRebind(
  current: ReadonlyMap<string, string>,
  commandId: string,
  binding: string,
  acknowledgedUnsafe = false,
): ReadonlyMap<string, string> {
  const before = current.get(commandId) ?? "";
  const next = new Map(current);
  next.set(commandId, binding);
  if (getCommand(commandId)?.destructive && before !== binding) {
    sink({
      action: TRADING_BINDING_CHANGED,
      commandId,
      before,
      after: binding,
      acknowledgedUnsafe,
    });
  }
  return next;
}

/**
 * Transmit a record to the server audit trail (POST /settings/hotkey-audit, C-2.9). The server
 * attributes it to the session principal and appends the hash-chained row. Records stay in the
 * outbox until the POST succeeds so a failed attempt can be flushed later.
 */
const AUDIT_PATH = "/api/v1/settings/hotkey-audit";
const outbox: AuditRecord[] = [];

export async function sendAudit(r: AuditRecord): Promise<boolean> {
  try {
    const res = await fetch(AUDIT_PATH, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        command_id: r.commandId,
        before: r.before,
        after: r.after,
        acknowledged_unsafe: r.acknowledgedUnsafe,
      }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function flushAuditOutbox(): Promise<void> {
  for (const r of [...outbox]) {
    if (await sendAudit(r)) outbox.splice(outbox.indexOf(r), 1);
  }
}

export function recordAudit(r: AuditRecord): void {
  outbox.push(r);
  void flushAuditOutbox();
}
export function auditOutbox(): readonly AuditRecord[] {
  return outbox;
}
