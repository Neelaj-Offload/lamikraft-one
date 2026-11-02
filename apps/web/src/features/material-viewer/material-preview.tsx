"use client";

import dynamic from "next/dynamic";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { cx } from "@/lib/cx";
import { LazyCanvas } from "@/lib/motion/lazy-canvas";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { slabDimensions } from "./geometry";
import { dragOrbit, matchingPreset, PRESETS, stepOrbit, type OrbitState, type PresetId } from "./orbit";
import { swatchForDecor } from "./swatches";
import type { MaterialSubject } from "./types";

// three, fiber and drei load only when the scene mounts (motion-system §5 lazy loading).
const MaterialScene = dynamic(() => import("./material-scene").then((mod) => mod.MaterialScene), { ssr: false });

const PRESET_LABELS: Record<PresetId, string> = { front: "Front", top: "Top", edge: "Edge" };

const COPY = {
  label: (name: string) => `3D preview of ${name}`,
  caption: "Material preview, not a product photo. The swatch is an illustrative fixture texture; the slab is sized from the product's specification.",
  sizedDefault: "The specification is incomplete, so a default slab size is shown.",
  keys: "Drag or use the arrow keys to turn the slab.",
  presets: "Preset views",
  none: "No material imagery is available for this product yet.",
} as const;

function dimensionsText(subject: MaterialSubject): string | null {
  const parts = [subject.length_mm, subject.width_mm, subject.thickness_mm].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? `${parts.join(" × ")} mm` : null;
}

/**
 * The product's Material view (motion-system §2): a slab at the product's real L × W × T,
 * textured with its decor swatch, rendered on demand. Orbit by drag, arrow keys or preset
 * buttons; the camera eases ≤ 600 ms to a preset. The scene mounts only once this panel is in
 * the viewport; before that, without WebGL, or on failure the static swatch stands in. Under
 * reduced motion the camera jumps between presets and drag/keys are not offered.
 */
export function MaterialPreview({ subject, className }: { subject: MaterialSubject; className?: string }) {
  const swatch = swatchForDecor(subject.decor_no, subject.decor_name, subject.product_name, subject.material_type);
  const reduced = useIsMotionReduced();
  const [orbit, setOrbit] = useState<OrbitState>(PRESETS.front);
  const [inView, setInView] = useState(false);
  const figure = useRef<HTMLElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const captionId = useId();
  const dims = slabDimensions(subject);

  useEffect(() => {
    const element = figure.current;
    if (!element || inView) return;
    if (typeof IntersectionObserver === "undefined") {
      // No observer support: mount the scene right away (one synchronous state set, once).
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setInView(true);
      },
      { rootMargin: "120px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [inView]);

  if (!swatch) return <p className={cx("text-ink-muted", className)}>{COPY.none}</p>;

  const name = subject.decor_name ?? swatch.label;
  const sizeText = dimensionsText(subject);
  const current = matchingPreset(orbit);
  // A static public asset shown while WebGL loads; next/image is kept off authenticated media (motion-system §5).
  // eslint-disable-next-line @next/next/no-img-element
  const fallback = <img src={swatch.albedo} alt="" width={1024} height={1024} className="h-full w-full object-cover" />;

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (reduced) return;
    drag.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const dx = event.clientX - drag.current.x;
    const dy = event.clientY - drag.current.y;
    drag.current = { x: event.clientX, y: event.clientY };
    setOrbit((state) => dragOrbit(state, dx, dy));
  };
  const onPointerUp = () => {
    drag.current = null;
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (reduced) return;
    const next = stepOrbit(orbit, event.key);
    if (!next) return;
    event.preventDefault();
    setOrbit(next);
  };

  return (
    <figure ref={figure} className={cx("flex flex-col gap-3", className)} aria-describedby={captionId}>
      <div
        role="group"
        aria-label={COPY.label(name)}
        aria-roledescription="3D viewer"
        tabIndex={reduced ? -1 : 0}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className={cx(
          "relative aspect-[4/3] w-full overflow-hidden rounded-lg border bg-surface-sunken outline-hidden focus-visible:focus-ring",
          !reduced && "cursor-grab touch-none active:cursor-grabbing",
        )}
      >
        {inView ? (
          <LazyCanvas
            label={COPY.label(name)}
            fallback={fallback}
            className="absolute inset-0"
            frameloop="demand"
            dpr={[1, 1.75]}
            shadows
            camera={{ fov: 32, near: 0.01, far: 20, position: [0.6, 0.5, 0.8] }}
          >
            <MaterialScene swatch={swatch} dims={dims} orbit={orbit} reduced={reduced} />
          </LazyCanvas>
        ) : (
          <div className="absolute inset-0">{fallback}</div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label={COPY.presets} className="flex gap-2">
          {(Object.keys(PRESETS) as PresetId[]).map((id) => (
            <Button key={id} size="sm" variant={current === id ? "primary" : "secondary"} aria-pressed={current === id} onPress={() => setOrbit(PRESETS[id])}>
              {PRESET_LABELS[id]}
            </Button>
          ))}
        </div>
        {!reduced ? <p className="text-sm text-ink-muted">{COPY.keys}</p> : null}
      </div>

      <figcaption id={captionId} className="flex flex-col gap-1 text-sm text-ink-muted">
        <span className="text-ink">
          <span className="font-semibold">{name}</span>
          {subject.decor_no ? <span className="font-mono"> · {subject.decor_no}</span> : null}
          {sizeText ? <span className="tabular"> · {sizeText}</span> : null}
          {subject.finish ? <span> · {subject.finish}</span> : null}
        </span>
        <span>{COPY.caption}</span>
        {!dims.complete ? <span>{COPY.sizedDefault}</span> : null}
      </figcaption>
    </figure>
  );
}
