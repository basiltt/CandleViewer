import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AdminInviteScreen } from "../../src/features/invites/AdminInviteScreen";
import { InviteAcceptScreen } from "../../src/features/invites/InviteAcceptScreen";

function reply(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe("InviteAcceptScreen (SCR-017)", () => {
  function mount(): void {
    render(
      <MemoryRouter initialEntries={["/invite/tok-0123456789abcdef"]}>
        <Routes>
          <Route path="/invite/:inviteToken" element={<InviteAcceptScreen />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("accepts an invite: password, TOTP, recovery codes", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, { display_name: "Ann", role: "viewer", expires_at: "x" }))
      .mockResolvedValueOnce(
        reply(200, { method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: "AAAA" }),
      )
      .mockResolvedValueOnce(
        reply(200, { status: "active", role: "viewer", recovery_codes: ["rc-1"] }),
      );
    vi.stubGlobal("fetch", f);
    mount();
    await screen.findByText(/Welcome, Ann/);
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "correct horse battery" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByLabelText("Authenticator code");
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate account" }));
    expect(await screen.findByText("rc-1")).toBeInTheDocument();
  });

  it("shows the uniform not-valid state for an expired link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, { detail: "x" })));
    mount();
    expect(await screen.findByText("Invitation not valid")).toBeInTheDocument();
    expect(screen.getByText(/re-issue it from Admin/)).toBeInTheDocument();
  });
});

describe("AdminInviteScreen (SCR-123)", () => {
  it("shows the link once with a copy control and the secret warning", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST")
        return reply(201, {
          id: "u1",
          username: "annie",
          invite_url: "/invite/abc",
          invite_expires_at: "2026-10-04T12:00:00+00:00",
        });
      void url;
      return reply(200, {
        items: [
          {
            user_id: "u2",
            username: "old",
            role: "viewer",
            expires_at: "2026-09-01T00:00:00+00:00",
            expired: true,
          },
        ],
      });
    });
    vi.stubGlobal("fetch", f);
    render(<AdminInviteScreen />);
    expect(await screen.findByText(/Expired - re-issue/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByText(/treat it as a secret/)).toBeInTheDocument();
    expect((screen.getByLabelText("Invite link") as HTMLInputElement).value).toContain(
      "/invite/abc",
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining("/invite/abc")),
    );
  });

  it("prompts for step-up when the server demands it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_u: string, init?: RequestInit) =>
        init?.method === "POST"
          ? reply(403, { code: "step_up_required" })
          : reply(200, { items: [] }),
      ),
    );
    render(
      <MemoryRouter>
        <AdminInviteScreen />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "annie" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
