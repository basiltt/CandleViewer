import { contextBridge, ipcRenderer } from "electron";
import { ALLOWED_IPC_CHANNELS, buildAllowList } from "./allowList.js";

/**
 * Exposes exactly one namespaced object, `window.cv`, built from the
 * explicit IPC allow-list (empty at E02-T04). contextIsolation is on, so
 * this is the only bridge between renderer and main.
 */
const cv = buildAllowList(ALLOWED_IPC_CHANNELS, (channel, ...args) =>
  ipcRenderer.invoke(channel, ...args),
);

contextBridge.exposeInMainWorld("cv", cv);
