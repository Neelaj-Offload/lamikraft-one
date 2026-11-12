"use client";

import type { Route } from "next";
import NextLink from "next/link";
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Radio, RadioGroup } from "react-aria-components";
import { cx } from "@/lib/cx";

/** Horizontal offset of `element` inside `container` (which must be positioned); ignores transforms. */
function offsetWithin(element: HTMLElement, container: HTMLElement): number {
  let left = 0;
  let node: HTMLElement | null = element;
  while (node && node !== container) {
    left += node.offsetLeft;
    node = node.offsetParent instanceof HTMLElement ? node.offsetParent : null;
  }
  return left;
}

const REVEAL_MARGIN = 16;

/**
 * Keeps a sliding selection mark (segmented thumb, tab ink bar) under the selected item.
 *
 * The mark is positioned by two custom properties written straight to the element, before paint
 * and again whenever sizes change (fonts arriving, a resize), so React never re-renders for it and
 * the mark never flashes at the wrong place. CSS does the slide. With `reveal`, a scrolling
 * container is also scrolled so the selected item is in view.
 *
 * Shared by `SegmentedControl` and `Tabs`; not part of the public barrel.
 */
export function useSlidingMark(
  containerRef: RefObject<HTMLElement | null>,
  markRef: RefObject<HTMLElement | null>,
  /** Matches the selected item inside the container. */
  selector: string,
  /** Any value that changes when the selection or the set of items changes. */
  selectionKey: string,
  reveal = false,
): void {
  const settled = useRef(false);
  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const place = () => {
      const mark = markRef.current;
      const selected = container.querySelector<HTMLElement>(selector);
      if (!mark) return selected;
      if (!selected) {
        delete mark.dataset.ready;
        return null;
      }
      mark.style.setProperty("--lk-thumb-left", `${offsetWithin(selected, container)}px`);
      mark.style.setProperty("--lk-thumb-width", `${selected.offsetWidth}px`);
      mark.dataset.ready = "true";
      return selected;
    };

    const selected = place();
    if (reveal && selected && container.scrollWidth > container.clientWidth) {
      const start = offsetWithin(selected, container) - REVEAL_MARGIN;
      const end = start + selected.offsetWidth + REVEAL_MARGIN * 2;
      let target: number | null = null;
      if (start < container.scrollLeft) target = Math.max(0, start);
      else if (end > container.scrollLeft + container.clientWidth) target = end - container.clientWidth;
      // The first placement jumps; later ones follow the container's CSS scroll-behavior.
      if (target !== null) container.scrollTo({ left: target, behavior: settled.current ? "auto" : "instant" });
    }
    settled.current = true;

    const observer = new ResizeObserver(place);
    observer.observe(container);
    for (const child of Array.from(container.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [containerRef, markRef, selector, selectionKey, reveal]);
}

export interface SegmentedOption {
  value: string;
  label: ReactNode;
}

interface SegmentedLook {
  size?: "sm" | "md";
  /** Frosted background, for a control that sits on imagery or the bare ground. */
  glass?: boolean;
  /** Names the group for assistive technology ("View", "Period"). */
  label: string;
  className?: string;
}

function segmentedClass({ size, glass, className }: Pick<SegmentedLook, "size" | "glass" | "className">): string {
  return cx("lk-seg", size === "sm" && "lk-seg-sm", glass && "lk-seg-glass", className);
}

export interface SegmentedControlProps extends SegmentedLook {
  options: SegmentedOption[];
  value?: string;
  /** Initial value when uncontrolled; the first option otherwise. */
  defaultValue?: string;
  onChange?: (value: string) => void;
  isDisabled?: boolean;
  /** Submits with a surrounding form under this name. */
  name?: string;
}

/**
 * A small set of mutually exclusive choices: a radio group (arrow keys move the choice) with the
 * ink thumb sliding to the selection.
 */
export function SegmentedControl({
  options,
  value,
  defaultValue,
  onChange,
  size = "md",
  glass = false,
  label,
  isDisabled,
  name,
  className,
}: SegmentedControlProps) {
  const [internal, setInternal] = useState(defaultValue ?? options[0]?.value);
  const current = value ?? internal;
  const groupRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLSpanElement>(null);
  useSlidingMark(groupRef, thumbRef, "[data-selected]", `${current}|${options.map((option) => option.value).join("|")}`);

  return (
    <RadioGroup
      ref={groupRef}
      aria-label={label}
      orientation="horizontal"
      name={name}
      isDisabled={isDisabled}
      value={current ?? null}
      onChange={(next) => {
        setInternal(next);
        onChange?.(next);
      }}
      className={segmentedClass({ size, glass, className })}
    >
      <span ref={thumbRef} className="lk-seg-thumb" aria-hidden="true" />
      {options.map((option) => (
        <Radio key={option.value} value={option.value} className="lk-seg-item">
          {option.label}
        </Radio>
      ))}
    </RadioGroup>
  );
}

export interface SegmentedLinkOption extends SegmentedOption {
  href: Route;
}

export interface SegmentedLinksProps extends SegmentedLook {
  options: SegmentedLinkOption[];
  /** The option the current URL shows. */
  value: string;
}

/** The segmented control for views that are URLs: links with the current one marked. */
export function SegmentedLinks({ options, value, size = "md", glass = false, label, className }: SegmentedLinksProps) {
  const navRef = useRef<HTMLElement>(null);
  const thumbRef = useRef<HTMLSpanElement>(null);
  useSlidingMark(navRef, thumbRef, '[aria-current="page"]', `${value}|${options.map((option) => option.value).join("|")}`);

  return (
    <nav ref={navRef} aria-label={label} className={segmentedClass({ size, glass, className })}>
      <span ref={thumbRef} className="lk-seg-thumb" aria-hidden="true" />
      {options.map((option) => (
        <NextLink
          key={option.value}
          href={option.href}
          className="lk-seg-item"
          aria-current={option.value === value ? "page" : undefined}
        >
          {option.label}
        </NextLink>
      ))}
    </nav>
  );
}
