/**
 * Masking for the on-demand screenshot (ai-routing §4.2). The capture is taken from the app's own
 * rendered DOM — never `getDisplayMedia`, so other windows and tabs can never be captured — and
 * works on a deep clone: every element marked `data-restricted` or `data-private`, and every
 * password field, is replaced in the clone by an opaque block of the same size. The live page is
 * never altered.
 */

export const MASK_SELECTOR = '[data-restricted], [data-private], input[type="password"]';
/** Elements never copied into the capture (scripts, the assistant's own capture chip, iframes). */
export const DROP_SELECTOR = "script, noscript, iframe, object, embed, template, [data-capture-exclude]";

export interface MaskCandidate {
  tagName: string;
  type?: string | null;
  hasAttribute: (name: string) => boolean;
}

/** The pure rule, for tests and for the cloner. */
export function shouldMask(element: MaskCandidate): boolean {
  if (element.hasAttribute("data-restricted") || element.hasAttribute("data-private")) return true;
  return element.tagName.toLowerCase() === "input" && (element.type ?? "").toLowerCase() === "password";
}

export interface MaskedClone {
  root: HTMLElement;
  maskedCount: number;
  width: number;
  height: number;
}

/** Layout properties copied onto a mask so it sits exactly where the hidden element was. */
const LAYOUT_PROPERTIES = [
  "position", "top", "right", "bottom", "left", "z-index", "margin-top", "margin-right", "margin-bottom", "margin-left",
  "float", "flex", "align-self", "justify-self", "grid-column", "grid-row", "transform",
] as const;

function opaqueBlock(doc: Document, width: number, height: number, display: string, layout: string): HTMLElement {
  const block = doc.createElement("div");
  block.setAttribute("data-capture-mask", "");
  block.setAttribute("aria-hidden", "true");
  block.style.cssText = [
    `display:${display === "inline" ? "inline-block" : display || "block"}`,
    `width:${Math.max(1, Math.floor(0.5 + width))}px`,
    `height:${Math.max(1, Math.floor(0.5 + height))}px`,
    "background:#1f2328",
    "border-radius:4px",
    "box-sizing:border-box",
    layout,
  ].join(";");
  return block;
}

/**
 * Clone `source` with masks applied. Sizes come from the live layout, so a masked block occupies
 * exactly the space of what it hides. Form values are copied into the clone (they are not part of
 * the serialised DOM) except for masked fields, whose content never enters the clone at all.
 */
export function cloneMasked(source: HTMLElement): MaskedClone {
  const doc = source.ownerDocument;
  const view = doc.defaultView;
  let maskedCount = 0;

  const copy = (node: Node): Node | null => {
    if (node.nodeType === Node.TEXT_NODE) return doc.createTextNode(node.textContent ?? "");
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const element = node as HTMLElement;
    if (element.matches(DROP_SELECTOR)) return null;
    if (shouldMask({ tagName: element.tagName, type: (element as HTMLInputElement).type, hasAttribute: (n) => element.hasAttribute(n) })) {
      maskedCount += 1;
      const rect = element.getBoundingClientRect();
      const computed = view?.getComputedStyle(element);
      const layout = computed ? LAYOUT_PROPERTIES.map((name) => `${name}:${computed.getPropertyValue(name)}`).join(";") : "";
      return opaqueBlock(doc, rect.width, rect.height, computed?.display ?? "block", layout);
    }
    const clone = element.cloneNode(false) as HTMLElement;
    if (element instanceof HTMLInputElement) {
      if (element.type === "checkbox" || element.type === "radio") clone.toggleAttribute("checked", element.checked);
      else clone.setAttribute("value", element.value);
    } else if (element instanceof HTMLTextAreaElement) {
      clone.textContent = element.value;
    } else if (element instanceof HTMLSelectElement) {
      clone.setAttribute("data-capture-value", element.value);
    }
    if (element instanceof HTMLTextAreaElement) return clone;
    for (const child of Array.from(element.childNodes)) {
      const copied = copy(child);
      if (copied) clone.appendChild(copied);
    }
    return clone;
  };

  const root = copy(source) as HTMLElement;
  const rect = source.getBoundingClientRect();
  return { root, maskedCount, width: Math.ceil(rect.width), height: Math.ceil(Math.min(rect.height, source.scrollHeight || rect.height)) };
}
