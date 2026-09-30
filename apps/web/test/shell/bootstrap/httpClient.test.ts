import { describe, expect, it, vi } from "vitest";
import { fetchJson, HttpError, HttpTimeoutError } from "../../../src/shell/bootstrap/httpClient.js";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("fetchJson", () => {
  it("resolves with the parsed JSON body on a 2xx response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const result = await fetchJson<{ ok: boolean }>("/api/v1/me", {
      timeoutMs: 1_000,
      fetchImpl,
    });
    expect(result).toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/me",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("throws HttpError with the status on a non-2xx response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 500));
    await expect(fetchJson("/api/v1/me", { timeoutMs: 1_000, fetchImpl })).rejects.toMatchObject({
      status: 500,
    });
  });

  it("throws HttpError as an instance", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 401));
    try {
      await fetchJson("/api/v1/me", { timeoutMs: 1_000, fetchImpl });
      expect.fail("expected rejection");
    } catch (error) {
      expect(error).toBeInstanceOf(HttpError);
    }
  });

  it("throws HttpTimeoutError when the request exceeds timeoutMs", async () => {
    const fetchImpl = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    });
    await expect(fetchJson("/api/v1/me", { timeoutMs: 5, fetchImpl })).rejects.toBeInstanceOf(
      HttpTimeoutError,
    );
  });
});
