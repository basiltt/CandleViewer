/**
 * `useShellState()` — the single read API for chrome components (ticket
 * scope). No component may fetch `/me`/`/me/preferences`/`/me/keymap`
 * itself; they all read this hook's synchronous snapshot instead.
 */
import { useSyncExternalStore } from "react";
import { getShellState, subscribeShellState, type ShellState } from "./bootstrap/store.js";

export function useShellState(): ShellState {
  return useSyncExternalStore(subscribeShellState, getShellState, getShellState);
}
