/**
 * Chart export utilities — v1.2.10 field fixes.
 *
 * The CorpusMind charts are hand-rolled inline SVGs colored with CSS
 * variables (var(--tool2-accent) …). A serialized standalone SVG cannot
 * resolve those custom properties — the rasterized PNG would come out
 * black-and-default — so before rasterizing we walk the live tree and
 * copy each element's COMPUTED presentation styles onto the clone. The
 * download then renders pixel-identical to the on-screen chart.
 *
 * CSV export escapes fields per RFC 4180 (quotes doubled, delimiters and
 * newlines quoted) and emits a UTF-8 BOM so Excel/Sheets open Arabic cell
 * text correctly.
 */

import { downloadBlob } from "@/lib/api";

const PRESENTATION_PROPS = [
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "opacity",
  "stop-color",
  "stop-opacity",
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "letter-spacing",
  "text-anchor",
  "dominant-baseline",
] as const;

/** First opaque ancestor background — pasting a dark-theme chart onto a
 * white document must stay legible, so the PNG always carries a backdrop. */
function resolveBackground(el: Element | null): string {
  let node: Element | null = el;
  while (node) {
    const bg = getComputedStyle(node).backgroundColor;
    if (bg && bg !== "transparent" && !bg.endsWith(", 0)")) return bg;
    node = node.parentElement;
  }
  return "#ffffff";
}

function inlineComputedStyles(source: Element, clone: Element): void {
  const computed = getComputedStyle(source);
  const style = (clone as SVGElement).style;
  for (const prop of PRESENTATION_PROPS) {
    const value = computed.getPropertyValue(prop);
    if (value) style.setProperty(prop, value);
  }
  const srcChildren = source.children;
  const dstChildren = clone.children;
  for (let i = 0; i < srcChildren.length && i < dstChildren.length; i += 1) {
    inlineComputedStyles(srcChildren[i], dstChildren[i]);
  }
}

/** Rasterize a live inline SVG to a PNG download at `scale`× resolution.
 * Uses the app-wide downloadBlob (native save dialog under Tauri, browser
 * download in the PWA). Returns the generated filename. */
export async function exportSvgAsPng(
  svg: SVGSVGElement,
  filename: string,
  scale = 2,
): Promise<string> {
  const rect = svg.getBoundingClientRect();
  const viewBox = svg.viewBox?.baseVal;
  const w = viewBox?.width || rect.width;
  const h = viewBox?.height || rect.height;
  if (!w || !h) throw new Error("chart export: chart has no measurable size");

  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(w));
  clone.setAttribute("height", String(h));
  inlineComputedStyles(svg, clone);

  const xml = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("chart export: SVG rasterization failed"));
      image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("chart export: canvas 2D context unavailable");
    ctx.fillStyle = resolveBackground(svg);
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/png"),
    );
    if (!blob) throw new Error("chart export: PNG encoding failed");
    await downloadBlob(blob, `${filename}.png`);
    return `${filename}.png`;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function csvField(v: unknown): string {
  const s = String(v ?? "");
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Download `rows` as an RFC-4180 CSV (UTF-8 BOM included). */
export function exportRowsAsCsv(
  headers: string[],
  rows: Array<Array<string | number>>,
  filename: string,
): string {
  const lines = [
    headers.map(csvField).join(","),
    ...rows.map((r) => r.map(csvField).join(",")),
  ];
  const blob = new Blob(["\uFEFF", lines.join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
  void downloadBlob(blob, `${filename}.csv`);
  return `${filename}.csv`;
}
