/**
 * Rasterise the masked clone of the visible page (ai-routing §4.2): the clone is wrapped in an SVG
 * `foreignObject` with the page's same-origin CSS and theme variables, drawn on a canvas at most
 * 1568 px on its longest edge, and encoded as WebP (PNG where the browser cannot encode WebP),
 * stepping the quality down until it is at most 1.5 MB. The SHA-256 lets the composer skip an
 * upload the conversation already has (the server deduplicates as well). Cross-origin images and
 * web fonts do not load inside the SVG; the capture shows the layout and text, not pixel-perfect art.
 */

import { cloneMasked } from "./mask";

export const MAX_EDGE_PX = 1568;
export const MAX_BYTES = 1_572_864;
const QUALITIES = [0.82, 0.7, 0.55, 0.4] as const;

export interface Capture {
  blob: Blob;
  width: number;
  height: number;
  maskedCount: number;
  sha256: string;
  routePath: string | null;
}

export class CaptureError extends Error {
  constructor(readonly reason: "unsupported" | "too_large" | "render_failed") {
    super(reason);
    this.name = "CaptureError";
  }
}

/** Longest edge at most `max`, never upscaled. */
export function scaleFor(width: number, height: number, max: number = MAX_EDGE_PX): number {
  const edge = Math.max(width, height);
  return edge > max ? max / edge : 1;
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

function pageCss(doc: Document): string {
  const parts: string[] = [];
  for (const sheet of Array.from(doc.styleSheets)) {
    try {
      for (const rule of Array.from(sheet.cssRules)) {
        if (rule instanceof CSSFontFaceRule) continue; // fonts cannot load inside an SVG image
        parts.push(rule.cssText);
      }
    } catch {
      // a cross-origin stylesheet: not readable, not needed for the app's own UI
    }
  }
  return parts.join("\n");
}

function rootVariables(doc: Document): string {
  const computed = doc.defaultView?.getComputedStyle(doc.documentElement);
  if (!computed) return "";
  const out: string[] = [];
  for (let i = 0; i < computed.length; i += 1) {
    const name = computed.item(i);
    if (name.startsWith("--")) out.push(`${name}:${computed.getPropertyValue(name)}`);
  }
  return out.join(";");
}

function toBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new CaptureError("render_failed"));
    image.src = src;
  });
}

/** Capture the visible part of `root` (default: the page body), masked. */
export async function captureMaskedScreen(root: HTMLElement = document.body): Promise<Capture> {
  if (typeof document === "undefined" || typeof XMLSerializer === "undefined") throw new CaptureError("unsupported");
  const doc = root.ownerDocument;
  const view = doc.defaultView!;
  const width = Math.max(1, Math.floor(0.5 + view.innerWidth));
  const height = Math.max(1, Math.floor(0.5 + view.innerHeight));
  const { root: clone, maskedCount } = cloneMasked(root);
  const bodyStyle = view.getComputedStyle(doc.body);

  const wrapper = doc.createElement("div");
  wrapper.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
  for (const attr of Array.from(doc.documentElement.attributes)) {
    if (attr.name === "class" || attr.name.startsWith("data-")) wrapper.setAttribute(attr.name, attr.value);
  }
  wrapper.style.cssText = [
    rootVariables(doc),
    `width:${width}px`,
    `height:${height}px`,
    "overflow:hidden",
    "position:relative",
    `background:${bodyStyle.backgroundColor || "#fff"}`,
    `color:${bodyStyle.color}`,
    `font-family:${bodyStyle.fontFamily}`,
    `font-size:${bodyStyle.fontSize}`,
  ].join(";");
  const style = doc.createElement("style");
  style.textContent = pageCss(doc);
  const page = doc.createElement("div");
  page.style.cssText = `position:absolute;left:0;top:0;width:${root.scrollWidth}px;transform:translate(${-view.scrollX}px,${-view.scrollY}px)`;
  page.appendChild(clone);
  wrapper.append(style, page);

  const markup = new XMLSerializer().serializeToString(wrapper);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><foreignObject x="0" y="0" width="100%" height="100%">${markup}</foreignObject></svg>`;
  const image = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);

  const scale = scaleFor(width, height);
  const canvas = doc.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(0.5 + width * scale));
  canvas.height = Math.max(1, Math.floor(0.5 + height * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new CaptureError("unsupported");
  context.fillStyle = bodyStyle.backgroundColor || "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  let blob: Blob | null = null;
  try {
    for (const quality of QUALITIES) {
      blob = await toBlob(canvas, "image/webp", quality);
      if (!blob) break;
      if (blob.type !== "image/webp") break; // no WebP encoder (Safari): PNG below
      if (blob.size <= MAX_BYTES) break;
    }
    if (!blob || blob.type !== "image/webp") blob = await toBlob(canvas, "image/png", 1);
  } catch {
    throw new CaptureError("render_failed"); // a tainted canvas or an encoder failure
  }
  if (!blob) throw new CaptureError("render_failed");
  if (blob.size > MAX_BYTES) throw new CaptureError("too_large");
  return {
    blob, width: canvas.width, height: canvas.height, maskedCount, sha256: await sha256Hex(blob),
    routePath: view.location?.pathname ?? null,
  };
}
