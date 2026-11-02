"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { SWATCHES, type Swatch } from "@/features/material-viewer/swatches";
import { cx } from "@/lib/cx";
import { authMessages as m } from "@/messages/auth";

/** motion-system §4 `parallax.max`: the front board moves at most this far. */
const PARALLAX_MAX_PX = 12;

interface Board {
  swatch: Swatch;
  decorNo: string;
  decorName: string;
  left: string;
  top: string;
  width: string;
  rotate: string;
  /** 0–1: how much of the pointer parallax this layer receives (front = 1). */
  depth: number;
}

/** Composition order: back to front. Decor numbers and names are the fixture decors. */
const BOARDS: readonly Board[] = [
  { swatch: SWATCHES.walnut, decorNo: "0457", decorName: "American Walnut", left: "6%", top: "9%", width: "62%", rotate: "-8deg", depth: 0.3 },
  { swatch: SWATCHES.ash, decorNo: "0415", decorName: "White Ash", left: "31%", top: "22%", width: "58%", rotate: "4deg", depth: 0.5 },
  { swatch: SWATCHES.maple, decorNo: "0310", decorName: "Hard Maple", left: "10%", top: "43%", width: "56%", rotate: "-3deg", depth: 0.75 },
  { swatch: SWATCHES.oak, decorNo: "0120", decorName: "Natural Oak", left: "33%", top: "57%", width: "54%", rotate: "6deg", depth: 1 },
];

/**
 * The sign-in composition: four material swatches stacked like boards on a bench, with real
 * shadows and a pointer parallax of at most 12 px on the front board (motion-system §2). The
 * entrance timeline animates the inner `[data-board]`; parallax moves the outer wrapper, so the
 * two never fight over one transform. Decorative: hidden from assistive technology, with the
 * honest caption shown to everyone.
 */
export function MaterialStage({ parallax, className }: { parallax: boolean; className?: string }) {
  const stage = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = stage.current;
    if (!element || !parallax) return;
    const layers = Array.from(element.querySelectorAll<HTMLElement>("[data-parallax]"));
    let frame = 0;
    let target: [number, number] = [0, 0];

    const apply = () => {
      frame = 0;
      for (const layer of layers) {
        const depth = Number.parseFloat(layer.dataset.parallax ?? "0");
        const x = target[0] * depth * PARALLAX_MAX_PX;
        const y = target[1] * depth * PARALLAX_MAX_PX;
        layer.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)`;
      }
    };
    const onMove = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect();
      // -1..1 from the stage centre; the movement is subtle by contract, never a tilt.
      target = [((event.clientX - rect.left) / rect.width) * 2 - 1, ((event.clientY - rect.top) / rect.height) * 2 - 1];
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    const onLeave = () => {
      target = [0, 0];
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerleave", onLeave);
    return () => {
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerleave", onLeave);
      if (frame) window.cancelAnimationFrame(frame);
      for (const layer of layers) layer.style.transform = "";
    };
  }, [parallax]);

  return (
    <div ref={stage} className={cx("relative isolate overflow-hidden bg-surface-sunken", className)}>
      <div aria-hidden="true" className="absolute inset-0">
        {BOARDS.map((board) => (
          <div
            key={board.swatch.id}
            data-parallax={board.depth}
            className="absolute aspect-[3/2] transition-transform duration-150 ease-standard will-change-transform"
            style={{ left: board.left, top: board.top, width: board.width }}
          >
            <div
              data-board=""
              className="relative h-full w-full"
              style={{ transform: `rotate(${board.rotate})`, "--board-rotate": board.rotate } as CSSProperties}
            >
              {/* The face: the swatch itself, with a real drop shadow. */}
              <div className="absolute inset-0 rounded-lg bg-cover bg-center shadow-lg" style={{ backgroundImage: `url(${board.swatch.albedo})` }} />
              {/* The visible edge of the board: a flat, darker strip, no gradient. */}
              <div className="absolute inset-x-0 -bottom-2 h-2.5 rounded-b-lg bg-ink/35" />
              <span className="absolute bottom-3 left-3 rounded-sm bg-surface px-2 py-1 font-mono text-[11px] text-ink shadow-sm">
                {board.decorName} · {board.decorNo}
              </span>
            </div>
          </div>
        ))}
      </div>
      <p className="absolute right-5 bottom-4 left-5 text-end text-xs text-ink-muted">{m.showcase.swatchNote}</p>
    </div>
  );
}

/** Below lg the stage is hidden; this row keeps the material cue under the headline. */
export function MaterialRow({ className }: { className?: string }) {
  return (
    <ul aria-hidden="true" className={cx("flex items-center gap-3", className)}>
      {BOARDS.map((board) => (
        <li key={board.swatch.id} className="flex items-center gap-2">
          <span className="size-9 rounded-sm bg-cover bg-center shadow-sm" style={{ backgroundImage: `url(${board.swatch.thumb})` }} />
          <span className="hidden text-xs text-ink-muted sm:inline">{board.decorName}</span>
        </li>
      ))}
    </ul>
  );
}
