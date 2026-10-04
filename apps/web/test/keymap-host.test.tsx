import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeymapHost, registerCommand } from "../src/keymap/KeymapHost";
import { HotkeyEditor } from "../src/keymap/HotkeyEditor";
import { Cheatsheet } from "../src/keymap/Cheatsheet";
import { setAuditSink, type AuditRecord } from "../src/keymap/audit";
import { getBindings, resetBindings, setBindings } from "../src/keymap/profile";

afterEach(() => {
  resetBindings();
  vi.useRealTimers();
});

describe("inert press explains itself (wired host)", () => {
  it("toasts once per 5s, executes nothing", () => {
    const run = vi.fn();
    const off = registerCommand("dom.cancel_all", run, () => false);
    render(
      <div data-keymap-context="DOM">
        <input aria-label="f" />
        <KeymapHost />
      </div>,
    );
    screen.getByLabelText("f").focus();
    for (let i = 0; i < 3; i++)
      fireEvent.keyDown(window, { key: "X", ctrlKey: true, shiftKey: true });
    expect(run).not.toHaveBeenCalled();
    const host = screen.getByTestId("toast-host");
    expect(host).toHaveAttribute("role", "status");
    expect(host.querySelectorAll("p")).toHaveLength(1);
    expect(host.textContent).toMatch(/Cancel all working orders/);
    off();
  });
  it("executes when valid", () => {
    const run = vi.fn();
    const off = registerCommand("dom.cancel_all", run);
    render(
      <div data-keymap-context="DOM">
        <input aria-label="f" />
        <KeymapHost />
      </div>,
    );
    screen.getByLabelText("f").focus();
    fireEvent.keyDown(window, { key: "X", ctrlKey: true, shiftKey: true });
    expect(run).toHaveBeenCalledTimes(1);
    off();
  });
});

describe("SCR-113 editor", () => {
  it("refuses conflict naming both, refuses reserved with platform, audits destructive rebind", () => {
    const audits: AuditRecord[] = [];
    setAuditSink((r) => audits.push(r));
    render(<HotkeyEditor />);
    const row = (label: string) => screen.getByText(label).closest("tr") as HTMLElement;
    const bind = (label: string, key: string, ctrlShift = false) => {
      const r = row(label);
      const inp = r.querySelector("input[type=text], input:not([type])") as HTMLInputElement;
      fireEvent.change(inp, { target: { value: key } });
      if (ctrlShift) {
        r.querySelectorAll("input[type=checkbox]").forEach((c, i) => i !== 1 && fireEvent.click(c));
      }
      fireEvent.click(r.querySelector("button") as HTMLElement);
    };
    bind("Cancel in-progress drawing", "I", true);
    expect(screen.getByRole("alert").textContent).toMatch(/reserved by/);
    bind("Delete selected drawing", "Esc");
    expect(screen.getByRole("alert").textContent).toMatch(/Cancel in-progress drawing/);
    bind("Cancel all working orders for symbol", "Q");
    expect(screen.getByRole("alert").textContent).toMatch(/destructive/);
    fireEvent.click(screen.getByText("I understand, bind anyway"));
    expect(getBindings().get("dom.cancel_all")).toBe("Q");
    expect(audits[0]).toMatchObject({ action: "hotkey.trading_binding_changed", after: "Q" });
  });
  it("import applies safe, lists unsafe", () => {
    render(<HotkeyEditor />);
    const ta = screen.getByLabelText("Import keymap JSON") as HTMLTextAreaElement;
    fireEvent.change(ta, {
      target: { value: JSON.stringify({ "dom.cancel_all": "Ctrl+Shift+I" }) },
    });
    fireEvent.blur(ta);
    expect(screen.getByLabelText("Import report").textContent).toMatch(/reserved/);
    expect(getBindings().get("dom.cancel_all")).not.toBe("Ctrl+Shift+I");
  });
});

describe("SCR-013 cheatsheet", () => {
  it("renders real tables and flags conflicts", () => {
    act(() => setBindings(new Map(getBindings()).set("chart.delete_drawing", "Esc")));
    render(<Cheatsheet />);
    expect(screen.getAllByRole("table").length).toBeGreaterThan(3);
    expect(screen.getByRole("link", { name: "Customise" })).toHaveAttribute(
      "href",
      "/settings/hotkeys",
    );
    expect(screen.getAllByLabelText(/conflicting binding/).length).toBeGreaterThan(0);
  });
});

describe("wiring (review fixes)", () => {
  it("Ctrl+/ opens the cheatsheet through the registered command", () => {
    render(<KeymapHost />);
    fireEvent.keyDown(window, { key: "/", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });
  it("default audit transport reaches the outbox", async () => {
    const { applyRebind, auditOutbox, setAuditSink } = await import("../src/keymap/audit");
    setAuditSink((r) => window.dispatchEvent(new CustomEvent("cv:audit", { detail: r })));
    render(<KeymapHost />);
    const n = auditOutbox().length;
    act(() => void applyRebind(getBindings(), "dom.cancel_all", "Q", true));
    expect(auditOutbox()).toHaveLength(n + 1);
    expect(auditOutbox()[n]).toMatchObject({ action: "hotkey.trading_binding_changed" });
  });
});

describe("audit is transmitted server-side", () => {
  it("POSTs hotkey.trading_binding_changed fields to /settings/hotkey-audit", async () => {
    const { applyRebind, recordAudit, auditOutbox } = await import("../src/keymap/audit");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    setAuditSink(recordAudit);
    applyRebind(new Map([["dom.cancel_all", "Ctrl+Shift+X"]]), "dom.cancel_all", "X", true);
    await vi.waitFor(() => expect(auditOutbox()).toHaveLength(0));
    const calls = fetchMock.mock.calls as [string, RequestInit][];
    expect(calls.every(([u]) => u === "/api/v1/settings/hotkey-audit")).toBe(true);
    const bodies = calls.map(([, i]) => JSON.parse(String(i.body)) as unknown);
    expect(bodies).toContainEqual({
      command_id: "dom.cancel_all",
      before: "Ctrl+Shift+X",
      after: "X",
      acknowledged_unsafe: true,
    });
    vi.unstubAllGlobals();
  });
});
