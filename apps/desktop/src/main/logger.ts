import { app } from "electron";
import fs from "node:fs";
import path from "node:path";

/**
 * Structured startup/audit logging (Observability section, E02-T04).
 * Precursor to E10's crash reporting and E04's build-info endpoint; never
 * logs secrets (C-12.6) — there is no secret material at this layer.
 */
function logLine(record: Record<string, unknown>): void {
  const line = JSON.stringify({ ts: new Date().toISOString(), ...record });
  try {
    const logDir = app.getPath("userData");
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(path.join(logDir, "shell.log"), `${line}\n`, "utf8");
  } catch {
    // Best-effort logging only; never let a logging failure crash the shell.
  }
  console.log(line);
}

export function logStartup(): void {
  logLine({
    event: "startup",
    appVersion: app.getVersion(),
    electronVersion: process.versions.electron,
    chromeVersion: process.versions.chrome,
    hardening: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
}

export function logAuditEvent(event: string, detail: Record<string, unknown>): void {
  logLine({ event, ...detail });
}
