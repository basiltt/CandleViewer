import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  DEFAULT_PREFERENCES,
  resolveFlags,
  resolveTriState,
  type A11yPreferences,
  type EngineFlags,
  type SystemMedia,
} from "./model";
import { loadPreferences, savePreferences } from "./prefsApi";

export interface PreferencesValue {
  readonly prefs: A11yPreferences;
  readonly media: SystemMedia;
  readonly flags: EngineFlags;
  readonly reducedMotion: boolean;
  readonly increasedContrast: boolean;
  readonly saveError: string | null;
  update: (patch: Partial<A11yPreferences>) => Promise<void>;
  retry: () => Promise<void>;
}

const Ctx = createContext<PreferencesValue | null>(null);

function readMedia(): SystemMedia {
  const m = typeof window !== "undefined" && window.matchMedia ? window.matchMedia : null;
  return {
    reducedMotion: m ? m("(prefers-reduced-motion: reduce)").matches : false,
    highContrast: m ? m("(prefers-contrast: more)").matches : false,
  };
}

export interface PreferencesProviderProps {
  readonly children: ReactNode;
  /** Receives plain-boolean flags on every change (the engine bridge); no scene rebuild. */
  readonly onEngineFlags?: (flags: EngineFlags) => void;
  readonly onChanged?: (key: string, value: unknown) => void;
}

export function PreferencesProvider(props: PreferencesProviderProps): JSX.Element {
  const { children, onEngineFlags, onChanged } = props;
  const [prefs, setPrefs] = useState<A11yPreferences>(DEFAULT_PREFERENCES);
  const [media, setMedia] = useState<SystemMedia>(readMedia);
  const [saveError, setSaveError] = useState<string | null>(null);
  const pending = useRef<Partial<A11yPreferences> | null>(null);

  useEffect(() => {
    let live = true;
    loadPreferences().then(
      (p) => {
        if (live) setPrefs(p);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const qs = [
      window.matchMedia("(prefers-reduced-motion: reduce)"),
      window.matchMedia("(prefers-contrast: more)"),
    ];
    const on = (): void => setMedia(readMedia());
    qs.forEach((q) => q.addEventListener("change", on));
    return () => qs.forEach((q) => q.removeEventListener("change", on));
  }, []);

  const flags = useMemo(() => resolveFlags(prefs, media), [prefs, media]);
  const reducedMotion = resolveTriState(prefs.reduced_motion, media.reducedMotion);
  const increasedContrast = resolveTriState(prefs.increased_contrast, media.highContrast);

  useEffect(() => {
    onEngineFlags?.(flags);
  }, [flags, onEngineFlags]);

  useEffect(() => {
    const r = document.documentElement;
    r.dataset["reducedMotion"] = String(reducedMotion);
    r.dataset["contrast"] = increasedContrast ? "more" : "normal";
    r.dataset["focusRing"] = prefs.thick_focus_ring ? "thick" : "normal";
    r.dataset["keyboardOnly"] = String(prefs.keyboard_only);
  }, [reducedMotion, increasedContrast, prefs.thick_focus_ring, prefs.keyboard_only]);

  const update = useCallback(
    async (patch: Partial<A11yPreferences>): Promise<void> => {
      const before = prefs;
      pending.current = patch;
      setPrefs({ ...before, ...patch }); // applies immediately (next frame)
      try {
        setPrefs(await savePreferences(patch));
        setSaveError(null);
        pending.current = null;
        for (const [k, v] of Object.entries(patch)) onChanged?.(k, v);
      } catch {
        setPrefs(before); // revert to the persisted value; never silently lie
        setSaveError("Could not save your accessibility preference.");
      }
    },
    [prefs, onChanged],
  );

  const retry = useCallback(async (): Promise<void> => {
    if (pending.current) await update(pending.current);
  }, [update]);

  const value: PreferencesValue = {
    prefs,
    media,
    flags,
    reducedMotion,
    increasedContrast,
    saveError,
    update,
    retry,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePreferences(): PreferencesValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("usePreferences requires PreferencesProvider");
  return v;
}
