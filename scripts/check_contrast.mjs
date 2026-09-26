#!/usr/bin/env node
/**
 * v1.2.7 (§1 dark-theme audit) — automated WCAG AA contrast regression check.
 *
 * Parses the design tokens out of web/src/styles/global.css (light + dark
 * theme blocks), resolves var() indirection, and asserts the token pairs the
 * UI depends on still meet their required contrast ratio. The tool-card hue
 * palette (8 hues × 2 themes × 4 interaction states) is checked explicitly —
 * a future "quick color tweak" that drops a cell below AA now fails CI
 * instead of shipping an unreadable state.
 *
 * Usage: node scripts/check_contrast.mjs
 * Exit codes: 0 = all pairs pass, 1 = one or more violations.
 *
 * Ratios are computed per WCAG 2.x relative luminance. Thresholds used:
 *   4.5  — normal-size text (WCAG 2.1 §1.4.3 AA)
 *   3.0  — large text & UI-component boundaries (WCAG 2.1 §1.4.11 AA)
 * Disabled UI is WCAG-exempt (1.4.3 "Inactive UI components"); the
 * --text-disabled tokens are reported for visibility but not asserted.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const CSS_PATH = join(repoRoot, "web", "src", "styles", "global.css");

// ---------------------------------------------------------------------- //
// Token parsing
// ---------------------------------------------------------------------- //

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function findBlock(css, selectorPattern, flags = "") {
  // Locate `selector { ... }` with brace-depth scanning (robust to nesting).
  const re = new RegExp(selectorPattern + "\\s*\\{", flags);
  const m = re.exec(css);
  if (!m) return null;
  let depth = 1;
  let i = m.index + m[0].length;
  const start = i;
  while (i < css.length && depth > 0) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") depth -= 1;
    i += 1;
  }
  if (depth !== 0) return null;
  return css.slice(start, i - 1);
}

function parseTokens(body) {
  const tokens = {};
  for (const line of body.split(";")) {
    const m = line.match(/(--[a-z0-9-]+)\s*:\s*([^;]+)/i);
    if (m) tokens[m[1]] = m[2].trim();
  }
  return tokens;
}

function hexToRgb(hex) {
  const h = hex.replace("#", "").trim();
  if (h.length === 3) {
    return [0, 1, 2].map((i) => parseInt(h[i] + h[i], 16) / 255);
  }
  if (h.length !== 6 || /[^0-9a-f]/i.test(h)) return null;
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}

function resolveColor(value, tokens, depth = 0) {
  if (depth > 8) return null;
  const v = value.trim();
  if (v.startsWith("#")) return hexToRgb(v);
  const varRef = v.match(/^var\(\s*(--[a-z0-9-]+)\s*(?:,\s*([^)]+))?\)$/i);
  if (varRef) {
    const name = varRef[1];
    if (name in tokens) return resolveColor(tokens[name], tokens, depth + 1);
    return varRef[2] ? resolveColor(varRef[2], tokens, depth + 1) : null;
  }
  return null; // rgb() / named colors are not used for the audited tokens
}

function luminance(rgb) {
  if (!rgb) return null;
  const [r, g, b] = rgb.map((c) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(fgNameOrValue, bgNameOrValue, tokens) {
  // Accept either raw color values or token names (looked up in `tokens`).
  const fgValue = fgNameOrValue.startsWith("--") ? tokens[fgNameOrValue] : fgNameOrValue;
  const bgValue = bgNameOrValue.startsWith("--") ? tokens[bgNameOrValue] : bgNameOrValue;
  const l1 = luminance(resolveColor(fgValue, tokens));
  const l2 = luminance(resolveColor(bgValue, tokens));
  if (l1 === null || l2 === null) return null;
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

// ---------------------------------------------------------------------- //
// Requirements
// ---------------------------------------------------------------------- //

const css = stripComments(readFileSync(CSS_PATH, "utf8"));

const baseBody = findBlock(css, "^:root", "m"); // brand/status/typography tokens
const lightBody = findBlock(css, ':root,\\s*\\[data-theme="light"\\]');
const darkBody = findBlock(css, '^\\[data-theme="dark"\\]', "m");
if (!lightBody || !darkBody || !baseBody) {
  console.error("FATAL: base/light/dark theme token blocks not found in global.css");
  process.exit(1);
}

const themes = {
  // Light theme = base :root tokens (brand, status, fonts) + the light block.
  light: { ...parseTokens(baseBody), ...parseTokens(lightBody) },
  dark: { ...parseTokens(baseBody), ...parseTokens(darkBody) },
};

// [foreground, background, min ratio, rationale]
const PAIRS = [
  ["--text", "--bg", 4.5, "body text on app background"],
  ["--text", "--bg-elevated", 4.5, "body text on cards/panels"],
  ["--text", "--bg-subtle", 4.5, "body text on subtle surfaces"],
  ["--text-muted", "--bg", 4.5, "secondary text on app background"],
  ["--text-muted", "--bg-elevated", 4.5, "secondary text on cards/panels"],
  ["--text-muted", "--bg-subtle", 4.5, "secondary text on subtle surfaces"],
  ["--brand-500", "--text-on-brand", 4.5, "primary button fill vs label"],
  ["--danger", "--bg", 4.5, "status text on background"],
  ["--success", "--bg", 4.5, "status text on background"],
  ["--warning", "--bg", 4.5, "status text on background"],
  ["--info", "--bg", 4.5, "status text on background"],
];

// Tool-card hue palette: 8 hues, per-theme, interaction-state pairs.
const TOOL_HUES = [1, 2, 3, 4, 5, 6, 7, 8];
const TOOL_PAIRS = [];
for (const n of TOOL_HUES) {
  TOOL_PAIRS.push(
    [`--tool${n}-accent`, "--tool-on-accent", 4.5,
      `tool${n} active fill: label on accent`],
    [`--tool${n}-accent`, `--tool${n}-soft`, 3.0,
      `tool${n} default state: accent icon on soft fill`],
    [`--tool${n}-accent`, "--bg-elevated", 3.0,
      `tool${n} icon on panel surface`],
    [`--tool${n}-border`, `--tool${n}-soft`, 1.15,
      `tool${n} idle card boundary visible (soft gate)`],
  );
}

let failures = 0;
let checked = 0;

for (const [theme, tokens] of Object.entries(themes)) {
  console.log(`\n=== ${theme} theme ===`);

  // Tokenized disabled state: reported, not asserted (WCAG 1.4.3 exemption
  // for inactive UI — but kept visible so future edits are a conscious act).
  const disabled = contrast("--text-disabled", "--bg", tokens);
  if (disabled !== null) {
    console.log(
      `  info  --text-disabled on --bg: ${disabled.toFixed(2)}:1 (WCAG-exempt, informational)`
    );
  }

  for (const [fg, bg, min, why] of [...PAIRS, ...TOOL_PAIRS]) {
    const ratio = contrast(fg, bg, tokens);
    if (ratio === null) {
      console.log(`  FAIL  ${fg} on ${bg} — ${why} (unresolvable color)`);
      failures += 1;
      checked += 1;
      continue;
    }
    checked += 1;
    if (ratio < min) {
      console.log(
        `  FAIL  ${fg} on ${bg}: ${ratio.toFixed(2)}:1 (needs ${min}:1) — ${why}`
      );
      failures += 1;
    }
  }
}

console.log(
  `\n${checked - failures}/${checked} token pairs pass.`
);

if (failures > 0) {
  console.error(`\n${failures} contrast violation(s) — token edits regressed WCAG AA.`);
  process.exit(1);
}
console.log("Contrast regression check: PASS");
