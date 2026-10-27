/**
 * Global keyboard shortcuts (frontend_verification §12, §16).
 * - "/" opens search when focus is not in a text field. It is a single-character shortcut,
 *   so it honours the user's `shortcuts_enabled` preference (WCAG 2.1.4).
 * - Ctrl+K / Cmd+K opens search from anywhere; it uses a modifier, so it always works.
 */

export interface ShortcutEvent {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey?: boolean;
  defaultPrevented?: boolean;
  isComposing?: boolean;
  target: EventTarget | null;
}

const TEXT_INPUT_TYPES = new Set(["text", "search", "email", "password", "tel", "url", "number", "date", "datetime-local", "time", "month", "week"]);

/** True when typing into the target should not trigger single-key shortcuts. */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const element = target as { tagName?: string; type?: string; isContentEditable?: boolean; getAttribute?: (name: string) => string | null };
  if (element.isContentEditable) return true;
  const tag = element.tagName?.toUpperCase();
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") return TEXT_INPUT_TYPES.has((element.type ?? "text").toLowerCase());
  // React Aria date segments and similar widgets are spinbuttons that take typed characters.
  return element.getAttribute?.("role") === "spinbutton" || element.getAttribute?.("role") === "textbox";
}

export function isSearchShortcut(event: ShortcutEvent, options: { shortcutsEnabled: boolean }): boolean {
  if (event.defaultPrevented || event.isComposing) return false;
  if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") return true;
  if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return false;
  return options.shortcutsEnabled && !isEditableTarget(event.target);
}
