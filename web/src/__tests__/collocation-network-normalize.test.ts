/**
 * collocation-network-normalize.test.ts — v1.2.14-9 (r9) field-report fix.
 *
 * Field report: on an Arabic corpus the collocation TABLE honored the
 * unification switch while the collocation NETWORK rendered empty — the
 * network client never sent normalize_arabic, the engine request model had
 * no such field, and neither did the network/table/keyness exports.
 *
 * Pinned here (client side): the api layer forwards the switch on
 *   - collocationNetwork / collocationNetworkExpand (interactive graph),
 *   - exportCollocationNetworkSvg / exportCollocationNetworkPng (diagram),
 *   - exportCollocations (flat table export),
 *   - exportKeyness (keyness export),
 * so the exported file / rendered graph is computed under the SAME
 * normalization as the on-screen table. Engine-side parity is covered by
 * engine/tests/test_r9_network_normalize.py (fail-before/pass-after).
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

function blobResponse(): Response {
  return {
    ok: true,
    status: 200,
    blob: async () => new Blob(["x"]),
  } as unknown as Response;
}

afterEach(() => {
  globalThis.fetch = REAL_FETCH;
  vi.restoreAllMocks();
});

async function lastBody(): Promise<Record<string, unknown>> {
  const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.at(-1)!;
  return JSON.parse(call[1].body as string);
}

describe("r9 collocation-network normalization parity", () => {
  it("sends normalize_arabic on the network build", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ params: {}, nodes: [], edges: [], stats: { nodes: 0, edges: 0, density: 0 } }),
    ) as unknown as typeof fetch;
    await api.collocationNetwork("c1", {
      node: "الاخبار", level: "word", window: 5, min_freq: 1,
      measure: "mi", normalize_arabic: true,
    });
    expect(await lastBody()).toMatchObject({ node: "الاخبار", normalize_arabic: true });
  });

  it("sends normalize_arabic on the network expand", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ params: {}, nodes: [], edges: [], new_nodes: [], stats: { nodes: 0, edges: 0, density: 0 } }),
    ) as unknown as typeof fetch;
    await api.collocationNetworkExpand("c1", {
      node: "الاخبار", level: "word", window: 5, min_freq: 1,
      measure: "mi", known_nodes: ["الاخبار"], normalize_arabic: true,
    });
    expect(await lastBody()).toMatchObject({ normalize_arabic: true, known_nodes: ["الاخبار"] });
  });

  it("omits the flag when unset (raw semantics preserved)", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse({ params: {}, nodes: [], edges: [], stats: { nodes: 0, edges: 0, density: 0 } }),
    ) as unknown as typeof fetch;
    await api.collocationNetwork("c1", {
      node: "ocean", level: "word", window: 5, min_freq: 1, measure: "mi",
    });
    const body = await lastBody();
    expect(body).not.toHaveProperty("normalize_arabic");
  });

  it("sends normalize_arabic on the SVG and PNG network exports", async () => {
    globalThis.fetch = vi.fn(async () => blobResponse()) as unknown as typeof fetch;
    await api.exportCollocationNetworkSvg("c1", "الاخبار", "word", 5, 1, true);
    expect(await lastBody()).toMatchObject({ normalize_arabic: true });
    await api.exportCollocationNetworkPng("c1", "الاخبار", "word", 5, 1, true);
    expect(await lastBody()).toMatchObject({ normalize_arabic: true });
  });

  it("sends normalize_arabic on the flat collocation and keyness exports", async () => {
    globalThis.fetch = vi.fn(async () => blobResponse()) as unknown as typeof fetch;
    await api.exportCollocations("c1", "الاخبار", "csv", "word", 5, 1, true);
    expect(await lastBody()).toMatchObject({ normalize_arabic: true });
    await api.exportKeyness("c1", "ref1", "xlsx", true);
    expect(await lastBody()).toMatchObject({ reference_corpus_id: "ref1", normalize_arabic: true });
  });
});
