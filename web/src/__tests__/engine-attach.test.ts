/**
 * engine-attach.test.ts — v1.2.15 runtime engine attachment.
 *
 * The hosted web app must be able to attach an engine at runtime (Settings →
 * Engine Connection) and route EVERY api call there. These tests pin the
 * resolution precedence implemented in lib/api.ts:
 *
 *     classroom session > runtime attachment > build-time base ("" / VITE_ENGINE_URL)
 *
 * Note: under vitest, import.meta.env.DEV is true, so engineAttached()
 * cannot return false in a test run — the "unattached" behaviour
 * (synthetic offline responses, zero network probes) is covered by the
 * v1.2.14-2 hosted-build hotfix. What matters here is the ORDER of
 * resolution and the persistence contract of the attachment.
 */
import { beforeEach, describe, expect, it } from "vitest";

import {
  clearAttachedEngine,
  clearStudentSession,
  getAttachedEngineToken,
  getAttachedEngineUrl,
  getEngineBase,
  setAttachedEngine,
  setStudentSession,
} from "@/lib/api";

describe("runtime engine attachment", () => {
  beforeEach(() => {
    clearAttachedEngine();
    clearStudentSession();
  });

  it("stores, normalizes, and reports the attached engine URL", () => {
    expect(getAttachedEngineUrl()).toBe("");
    setAttachedEngine("http://127.0.0.1:8765/");
    expect(getAttachedEngineUrl()).toBe("http://127.0.0.1:8765");
    expect(getEngineBase()).toBe("http://127.0.0.1:8765");
  });

  it("keeps the token alongside the URL and clears both on detach", () => {
    setAttachedEngine("http://127.0.0.1:8765", "tok-1");
    expect(getAttachedEngineToken()).toBe("tok-1");
    clearAttachedEngine();
    expect(getAttachedEngineUrl()).toBe("");
    expect(getAttachedEngineToken()).toBe("");
  });

  it("an empty attach call removes a previous attachment", () => {
    setAttachedEngine("http://127.0.0.1:8765");
    setAttachedEngine("");
    expect(getEngineBase()).toBe("");
  });

  it("classroom session wins over the runtime attachment", () => {
    setAttachedEngine("http://127.0.0.1:8765");
    setStudentSession("http://classroom.local:9443", "student-tok");
    expect(getEngineBase()).toBe("http://classroom.local:9443");
    clearStudentSession();
    expect(getEngineBase()).toBe("http://127.0.0.1:8765");
  });

  it("falls back to the build-time base (same-origin empty string) when nothing is attached", () => {
    expect(getEngineBase()).toBe("");
  });
});
