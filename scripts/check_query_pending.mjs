#!/usr/bin/env node
/**
 * check_query_pending.mjs — CI guard (v1.2.12-rc7).
 *
 * Bug class: in TanStack Query v5 a query that has not run yet (`enabled:
 * false`) reports `isPending === true` (fetchStatus "idle"). Using
 * `query.isPending` as an "in flight" flag therefore shows a permanent
 * "Analyzing…" state and disables the action button before the user ever
 * clicks (field report: Arabic Tools stuck on "Analyzing… 0s"). tsc cannot
 * see this. Use `isFetching` (any fetch) or `isLoading` (first fetch).
 *
 * Fails when `X.isPending` is read where X is a `useQuery(...)` result whose
 * options contain `enabled:`. `useMutation` results are fine (isPending is the
 * correct in-flight flag there) and un-gated queries are fine.
 *
 * Test files are exempt — they may intentionally construct the bug class to
 * prove the regression tests fail without the fix.
 *
 * Escape hatch (rare, must be justified): append `// pending-ok: <reason>`
 * to the offending line.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("../web/src/", import.meta.url).pathname;
const files = [];
(function walk(d) {
  for (const n of readdirSync(d)) {
    const p = join(d, n);
    if (statSync(p).isDirectory()) { if (n !== "__harness__" && n !== "__tests__" && n !== "__mocks__") walk(p); }
    else if (/\.tsx?$/.test(n) && !/\.(test|spec)\.[jt]sx?$/.test(n)) files.push(p);
  }
})(ROOT);

const bad = [];
for (const f of files) {
  const src = readFileSync(f, "utf8");
  const gated = new Set();
  const declRe = /const\s+(\w+)\s*=\s*useQuery\s*[<(]/g;
  let m;
  while ((m = declRe.exec(src))) {
    let depth = 0, i = m.index + m[0].length - 1, end = -1;
    for (; i < src.length; i++) {
      const c = src[i];
      if (c === "(" || c === "{" || c === "[") depth++;
      else if (c === ")" || c === "}" || c === "]") { depth--; if (depth === 0) { end = i; break; } }
    }
    if (end > 0 && /\benabled\s*:/.test(src.slice(m.index, end))) gated.add(m[1]);
  }
  const lines = src.split("\n");
  lines.forEach((ln, idx) => {
    for (const v of gated) {
      if (new RegExp(`\\b${v}\\.isPending\\b`).test(ln) && !/pending-ok:/.test(ln))
        bad.push(`${relative(ROOT, f)}:${idx + 1}  ${v}.isPending on an enabled-gated useQuery`);
    }
  });
}

if (bad.length) {
  console.error("isPending misuse (true before an enabled-gated query ever runs):\n  " + bad.join("\n  "));
  console.error("\nUse isFetching (in flight) or isLoading (first fetch in flight).");
  process.exit(1);
}
console.log(`query-pending guard: PASS (${files.length} files scanned)`);
