/**
 * boot-transport-error.test.ts — v1.2.14-7 (r7) boot-race + raw-transport-error fixes.
 *
 * Two defects were reported against r6: on every launch the shell minted two
 * Smart Troubleshooting cards with the Tauri HTTP plugin's raw reqwest text —
 *   "error sending request for url (http://127.0.0.1:8765/api/v1/corpora/<id>)"
 *   "error sending request for url (http://127.0.0.1:8765/api/v1/providers)"
 *
 * Root causes pinned here:
 *   1. Boot-time queries (sidebar active-corpus pill, HomeView provider chips)
 *      fired before the PyInstaller sidecar had bound its port. jsonFetch now
 *      gates the first non-health call behind a successful /health answer.
 *   2. plugin-http rejects with a bare STRING, not an Error — e.message is
 *      undefined, so jsonFetch's connection-error classification failed and
 *      rethrew the raw string, bypassing both the self-heal probe and
 *      friendlyEngineError. Both classification sites now normalize first.
 *
 * NOTE: `api` is imported statically (the engine-attach.test.ts pattern).
 * jsonFetch's _engineReady flag latches true after the first successful
 * health probe, so test ORDER matters: the first test exercises the gate
 * itself; later tests run post-latch and pin classification behaviour,
 * which is gate-independent.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

const REAL_FETCH = globalThis.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  globalThis.fetch = REAL_FETCH;
  vi.restoreAllMocks();
});

describe("r7 boot transport-error fixes", () => {
  it("gates the first non-health call behind a successful health probe", async () => {
    const order: string[] = [];
    (globalThis as any).fetch = vi.fn(async (url: string) => {
      order.push(url);
      if (url.includes("/api/v1/health")) return jsonResponse({ status: "ok" });
      return jsonResponse({ corpus_id: "abc", name: "Test corpus" });
    });

    const corpus = await api.getCorpus("abc");
    expect(corpus.name).toBe("Test corpus");
    // The readiness probe must precede the real endpoint.
    expect(order[0]).toContain("/api/v1/health");
    expect(order.some((u) => u.includes("/api/v1/corpora/abc"))).toBe(true);
  });

  it("wraps raw string rejections from the transport in the friendly engine error", async () => {
    (globalThis as any).fetch = vi.fn(async (url: string) => {
      if (url.includes("/api/v1/health")) return jsonResponse({ status: "ok" });
      // Exactly what plugin-http throws on connection refusal: a bare string.
      throw "error sending request for url (http://127.0.0.1:8765/api/v1/corpora/59da0b5d4f384d0f)";
    });

    const err = await api.getCorpus("59da0b5d4f384d0f").catch((e) => e);
    expect(String(err)).toMatch(/analysis engine is not responding/i);
    // The raw plugin text must never reach an error card.
    expect(String(err)).not.toMatch(/error sending request/);
  });

  it("wraps Error-instance transport failures the same way", async () => {
    (globalThis as any).fetch = vi.fn(async (url: string) => {
      if (url.includes("/api/v1/health")) return jsonResponse({ status: "ok" });
      throw new Error("Failed to fetch");
    });

    const err = await api.providers().catch((e) => e);
    expect(String(err)).toMatch(/analysis engine is not responding/i);
  });

  it("passes HTTP-status errors through untouched", async () => {
    (globalThis as any).fetch = vi.fn(async (url: string) => {
      if (url.includes("/api/v1/health")) return jsonResponse({ status: "ok" });
      return jsonResponse({ detail: "Corpus not found" }, 404);
    });

    const err = await api.getCorpus("gone").catch((e) => e);
    expect(String(err)).toContain("HTTP 404");
    expect(String(err)).not.toMatch(/not responding/i);
  });

  it("keeps /health immediate and retrying — never gated behind itself", async () => {
    let healthCalls = 0;
    (globalThis as any).fetch = vi.fn(async (url: string) => {
      if (url.includes("/api/v1/health")) {
        healthCalls += 1;
        if (healthCalls === 1) {
          throw "error sending request for url (http://127.0.0.1:8765/api/v1/health)";
        }
        return jsonResponse({ status: "ok" });
      }
      return jsonResponse({});
    });

    // /health is a startup endpoint: no readiness gate, its own retry budget.
    const h = await api.health();
    expect(h.status).toBe("ok");
    expect(healthCalls).toBeGreaterThanOrEqual(2);
  });
});
