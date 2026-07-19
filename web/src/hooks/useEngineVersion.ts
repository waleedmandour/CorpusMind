/**
 * useEngineVersion — shared hook that fetches the engine version from
 * GET /api/v1/version and returns it as a display string (e.g. "v0.1.8").
 *
 * FIX 8: Previously the version string was hardcoded independently in four
 * places (Sidebar, HomeView, AboutView x2), which had already drifted out
 * of sync once in this project's history. This hook centralizes the source
 * of truth: the engine's own /version endpoint. All UI components should
 * use this hook instead of a hardcoded literal.
 *
 * Falls back to the hardcoded default while the query is loading, so there's
 * no layout flash to an empty string on first paint.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** The fallback version shown while the engine version query is loading
 *  or when the engine is unreachable. Must match the version in
 *  desktop/src-tauri/tauri.conf.json + engine/pyproject.toml. */
const FALLBACK_VERSION = "0.1.8";

export function useEngineVersion(): string {
  const query = useQuery({
    queryKey: ["version"],
    queryFn: api.version,
    staleTime: Infinity, // version doesn't change during a session
    retry: false,
  });
  // Return the engine's version if available, otherwise the fallback.
  // The engine returns { version: "0.1.8", name: "corpusmind-engine" }
  return query.data?.version ?? FALLBACK_VERSION;
}

/** Returns the version with a leading "v" (e.g. "v0.1.8") for display. */
export function useEngineVersionDisplay(): string {
  const version = useEngineVersion();
  return version.startsWith("v") ? version : `v${version}`;
}
