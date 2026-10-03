import { describe, expect, it } from "vitest";
import {
  KEYMAP,
  SAFETY_MODIFIER_DEFAULT,
  bindingFor,
  eventBinding,
  getCommand,
  matchesCommand,
} from "../src/keymap/keymap";

type Mods = Partial<Record<"ctrlKey" | "metaKey" | "altKey" | "shiftKey", boolean>>;
const ev = (key: string, o: Mods = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...o,
});

describe("keymap source of truth", () => {
  it("has unique command ids and the safety default on", () => {
    expect(new Set(KEYMAP.map((c) => c.id)).size).toBe(KEYMAP.length);
    expect(SAFETY_MODIFIER_DEFAULT).toBe(true);
  });

  it("never gives a destructive command a bare single-letter binding", () => {
    for (const c of KEYMAP.filter((k) => k.destructive)) {
      expect(c.defaultBinding).not.toMatch(/^[A-Za-z]$/);
    }
  });

  it("resolves bindings by id and throws on unknown ids", () => {
    expect(bindingFor("global.palette")).toBe("Ctrl+K");
    expect(getCommand("nope")).toBeUndefined();
    expect(() => bindingFor("nope")).toThrow(/Unknown keymap command/);
  });

  it("normalises keyboard events (Cmd folds to Ctrl, named keys)", () => {
    expect(eventBinding(ev("k", { metaKey: true }))).toBe("Ctrl+K");
    expect(eventBinding(ev("Escape"))).toBe("Esc");
    expect(eventBinding(ev("ArrowLeft", { shiftKey: true, ctrlKey: true }))).toBe("Ctrl+Shift+←");
    expect(eventBinding(ev("F11"))).toBe("F11");
  });

  it("matches exact and digit-range bindings", () => {
    expect(matchesCommand("global.palette", ev("k", { ctrlKey: true }))).toBe(true);
    expect(matchesCommand("global.palette", ev("j", { ctrlKey: true }))).toBe(false);
    expect(matchesCommand("global.nav_rail", ev("3", { altKey: true }))).toBe(true);
    expect(matchesCommand("global.nav_rail", ev("3"))).toBe(false);
    expect(matchesCommand("global.nav_rail", ev("a", { altKey: true }))).toBe(false);
    expect(matchesCommand("ticket.qty_preset", ev("5"))).toBe(false);
    expect(matchesCommand("ticket.qty_preset", ev("4"))).toBe(true);
  });
});
