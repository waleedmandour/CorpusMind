/**
 * student-engine-attached.test.ts — v1.2.14-8 (r8) P0-4 regression.
 *
 * Field report: a STUDENT browser (DEV=false production build, non-Tauri,
 * classroom session in localStorage) saw the "engine offline" badge and
 * false provider chips. Root cause: getEngineBase() routes student calls
 * to the student server (classroom > attached > build-time base), but
 * engineAttached() never consulted the student session — so every
 * always-on status probe short-circuited to a synthetic OFFLINE response
 * while the student's actual data calls worked fine. The status UI lied.
 *
 * Contract pinned here (fail-before / pass-after):
 *   1. With a student session and DEV=false: engineAttached() is true and
 *      api.health() issues exactly ONE request to the STUDENT server.
 *   2. With no session at all and DEV=false: engineAttached() stays false
 *      and health() issues ZERO network calls (the v1.2.14-2 hosted
 *      hotfix contract — synthetic offline, no phantom 404s).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAttachedEngine,
  clearStudentSession,
  engineAttached,
  setStudentSession,
} from "@/lib/api";

describe("student session implies an attached engine (r8 P0-4)", () => {
  const realDev = import.meta.env.DEV;
  const fetchMock = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) =>
    new Response(JSON.stringify({ status: "ok", engine: "corpusmind-engine" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );

  beforeEach(() => {
    import.meta.env.DEV = false; // production hosted build
    clearAttachedEngine();
    clearStudentSession();
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    import.meta.env.DEV = realDev;
    vi.unstubAllGlobals();
    clearStudentSession();
  });

  it("student session → engineAttached() true, health probes the student server once", async () => {
    setStudentSession("http://classroom.local:9443/", "student-tok");

    expect(engineAttached()).toBe(true);

    const { api } = await import("@/lib/api");
    await api.health();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toBe("http://classroom.local:9443/api/v1/health");
  });

  it("no session, DEV=false, non-Tauri → still unattached, zero network probes", async () => {
    expect(engineAttached()).toBe(false);

    const { api } = await import("@/lib/api");
    await api.health();

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
