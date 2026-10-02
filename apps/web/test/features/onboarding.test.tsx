import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SetupChecklistCard } from "../../src/features/onboarding/SetupChecklistCard";
import { formatCountdown } from "../../src/features/onboarding/checklistApi";

const KEYS = ["tailscale", "totp", "sub_account", "api_key", "profile_limits", "demo_session"];
function item(key: string, state: string, extra: object = {}): object {
  return { key, state, reason: null, unblock_at: null, action_route: "/x", ...extra };
}
function reply(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}
function all(state: string): object[] {
  return KEYS.map((k) => item(k, state));
}
afterEach(() => vi.unstubAllGlobals());

describe("SetupChecklistCard", () => {
  it("renders six steps with state as text", async () => {
    const body = { complete: false, dismissed: false, items: all("pending") };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(body)));
    render(<SetupChecklistCard />);
    expect(await screen.findAllByRole("listitem")).toHaveLength(6);
    expect(screen.getAllByText("Pending")).toHaveLength(6);
  });

  it("shows the 48h restriction with a countdown and demo offer", async () => {
    const at = new Date(Date.now() + 3 * 3_600_000).toISOString();
    const items = KEYS.map((k) =>
      k === "api_key"
        ? item(k, "blocked", { reason: "Bybit blocks keys", unblock_at: at })
        : item(k, "ok"),
    );
    const body = { complete: false, dismissed: false, items };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(body)));
    render(<SetupChecklistCard />);
    expect(await screen.findByText(/left\)/)).toBeTruthy();
    expect(screen.getByText(/Demo exploration/)).toBeTruthy();
  });

  it("error step offers retry while the rest still render", async () => {
    const items = KEYS.map((k) => item(k, k === "totp" ? "error" : "ok"));
    const f = vi.fn().mockResolvedValue(reply({ complete: false, dismissed: false, items }));
    vi.stubGlobal("fetch", f);
    render(<SetupChecklistCard />);
    fireEvent.click(await screen.findByRole("button", { name: /Retry TOTP/ }));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2));
  });

  it("completed card dismisses and persists via POST", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply({ complete: true, dismissed: false, items: all("ok") }))
      .mockResolvedValueOnce(reply({}));
    vi.stubGlobal("fetch", f);
    const { container } = render(<SetupChecklistCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(container.textContent).toBe(""));
    expect(String(f.mock.calls[1]?.[0])).toContain("/dismiss");
  });

  it("renders nothing when the service is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    const { container } = render(<SetupChecklistCard />);
    await waitFor(() => expect(container.textContent).toBe(""));
  });
});

describe("formatCountdown", () => {
  it("formats hours and minutes in UTC and clamps at zero", () => {
    const now = new Date("2026-10-01T00:00:00Z");
    expect(formatCountdown("2026-10-02T01:30:30Z", now)).toBe("25h 30m");
    expect(formatCountdown("2026-09-30T00:00:00Z", now)).toBe("0h 0m");
  });
});

describe("SCR-018 coach marks", () => {
  it("auto-shows once, steps through 8 stops, Esc exits and is not shown again", async () => {
    window.localStorage.clear();
    const body = { complete: false, dismissed: false, items: all("pending") };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(body)));
    const { unmount } = render(<SetupChecklistCard />);
    const dlg = await screen.findByRole("dialog");
    expect(dlg.getAttribute("aria-label")).toContain("1 of 8");
    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByRole("dialog").getAttribute("aria-label")).toContain("2 of 8");
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    unmount();
    render(<SetupChecklistCard />);
    await screen.findAllByRole("listitem");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByText("Take the tour"));
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("does not auto-offer the tour once the checklist is complete", async () => {
    window.localStorage.clear();
    const body = { complete: true, dismissed: false, items: all("ok") };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(body)));
    render(<SetupChecklistCard />);
    await screen.findByText("Setup complete.");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
