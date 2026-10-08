// Allow-list preload (sandboxed: only electron's contextBridge may be required here).
// Exposes a single read-only marker so the page can label the shell; NO generic IPC,
// NO Node surface (SR-111 pattern from apps/desktop/src/preload/allowList.ts).
"use strict";
const { contextBridge } = require("electron");
contextBridge.exposeInMainWorld("cvMatrixShell", Object.freeze({ kind: "electron" }));
