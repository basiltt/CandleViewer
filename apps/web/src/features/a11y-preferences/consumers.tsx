import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { usePreferences } from "./PreferencesContext";
import type { EngineFlags } from "./model";

/** True when keyboard-only mode is on (drag-only affordances hidden, equivalents revealed). */
export function useKeyboardOnly(): boolean {
  return usePreferences().prefs.keyboard_only;
}

/** Renders children only while a drag-only affordance is allowed (keyboard-only mode off). */
export function DragOnly({ children }: { readonly children: ReactNode }): JSX.Element | null {
  return useKeyboardOnly() ? null : <>{children}</>;
}

/** Renders children (nudge controls, numeric fields, "..." menus) only in keyboard-only mode. */
export function KeyboardEquivalent({
  children,
}: {
  readonly children: ReactNode;
}): JSX.Element | null {
  return useKeyboardOnly() ? <>{children}</> : null;
}

/** Default panel view honouring "always show data-table alternatives"; no data is re-fetched. */
export function useDefaultPanelView(): "table" | "chart" {
  return usePreferences().prefs.always_show_tables ? "table" : "chart";
}

export interface PanelResizeControlProps {
  readonly label: string;
  readonly value: number;
  readonly min: number;
  readonly max: number;
  readonly step?: number;
  readonly onChange: (v: number) => void;
}

/** Panel resize: drag handle normally; nudge buttons + numeric field in keyboard-only mode. */
export function PanelResizeControl(p: PanelResizeControlProps): JSX.Element {
  const step = p.step ?? 10;
  const clamp = (v: number): number => Math.min(p.max, Math.max(p.min, v));
  return (
    <div>
      <DragOnly>
        <div role="separator" aria-label={`${p.label} drag handle`} data-drag-handle="true" />
      </DragOnly>
      <KeyboardEquivalent>
        <button type="button" onClick={() => p.onChange(clamp(p.value - step))}>
          {`Decrease ${p.label}`}
        </button>
        <label>
          {`${p.label} (px)`}
          <input
            type="number"
            value={p.value}
            min={p.min}
            max={p.max}
            onChange={(e) => p.onChange(clamp(Number(e.target.value)))}
          />
        </label>
        <button type="button" onClick={() => p.onChange(clamp(p.value + step))}>
          {`Increase ${p.label}`}
        </button>
      </KeyboardEquivalent>
    </div>
  );
}

/**
 * Engine bridge: holds the latest plain-boolean flags; the render loop reads `get()` per
 * frame (no React, no scene rebuild) and `subscribe` notifies a worker `postMessage` adapter.
 */
export interface EngineFlagsChannel {
  get: () => EngineFlags | null;
  subscribe: (fn: (f: EngineFlags) => void) => () => void;
  publish: (f: EngineFlags) => void;
}

export function createEngineFlagsChannel(): EngineFlagsChannel {
  let current: EngineFlags | null = null;
  const subs = new Set<(f: EngineFlags) => void>();
  return {
    get: () => current,
    subscribe: (fn) => {
      subs.add(fn);
      if (current) fn(current);
      return () => void subs.delete(fn);
    },
    publish: (f) => {
      current = f;
      subs.forEach((fn) => fn(f));
    },
  };
}

export const engineFlagsChannel: EngineFlagsChannel = createEngineFlagsChannel();

/** Stable callback for `PreferencesProvider.onEngineFlags` publishing to the shared channel. */
export function usePublishEngineFlags(): (f: EngineFlags) => void {
  const [ch] = useState(() => engineFlagsChannel);
  return useCallback((f) => ch.publish(f), [ch]);
}

/** Structural subset of the chart-engine handle (avoids coupling to engine internals). */
export interface FlagsTarget {
  setFlags(f: EngineFlags): void;
}

/** Forwards every published flag set to an engine handle; returns the unsubscribe. */
export function bindEngineFlags(
  engine: FlagsTarget,
  channel: EngineFlagsChannel = engineFlagsChannel,
): () => void {
  return channel.subscribe((f) => engine.setFlags(f));
}

export interface AccessiblePanelProps {
  readonly title: string;
  readonly chart: ReactNode;
  readonly table: ReactNode;
}

/**
 * Panel that renders the chart or its data-table alternative. "Always show data tables"
 * makes the table the default view; a toggle lets the user switch either way (no refetch).
 */
export function AccessiblePanel(p: AccessiblePanelProps): JSX.Element {
  const dflt = useDefaultPanelView();
  const [override, setOverride] = useState<"table" | "chart" | null>(null);
  const view = override ?? dflt;
  return (
    <section aria-label={p.title}>
      <button
        type="button"
        aria-pressed={view === "table"}
        onClick={() => setOverride(view === "table" ? "chart" : "table")}
      >
        {view === "table" ? "Show chart" : "Show data table"}
      </button>
      {view === "table" ? p.table : p.chart}
    </section>
  );
}
