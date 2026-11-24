"use client";

import dynamic from "next/dynamic";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { slabDimensions } from "@/features/material-viewer/geometry";
import { dragOrbit, matchingPreset, PRESETS, stepOrbit, type OrbitState, type PresetId } from "@/features/material-viewer/orbit";
import type { ProductDetail } from "@/features/products/types";
import { formatDecimal } from "@/lib/format/money";
import { LazyCanvas } from "@/lib/motion/lazy-canvas";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { useZone } from "@/lib/session/context";
import { PageSection } from "~/shell/page";
import { EmptyState, GlassPanel, SegmentedControl } from "~/ui";
import { decorSwatch } from "./swatch";

/**
 * The material view: the product's decor on a slab of its real length, width and thickness.
 *
 * The three.js scene is the old app's `MaterialScene`, loaded as it is and only when this panel
 * is on screen (the one old view component this area reuses). Everything around it is new: the
 * glass frame, the preset control and the still image that stands in while WebGL loads, when it
 * is unavailable, or if the scene fails.
 */
const MaterialScene = dynamic(() => import("@/features/material-viewer/material-scene").then((mod) => mod.MaterialScene), { ssr: false });

const PRESET_OPTIONS: { value: PresetId; label: string }[] = [
  { value: "front", label: "Front" },
  { value: "top", label: "Top" },
  { value: "edge", label: "Edge" },
];

export function ProductMaterial({ product }: { product: ProductDetail }) {
  const { locale } = useZone();
  const spec = product.specification;
  // Specification millimetres first; the product's own size when the specification has none.
  const measures = {
    length_mm: spec?.length_mm ?? product.size.length_mm,
    width_mm: spec?.width_mm ?? product.size.width_mm,
    thickness_mm: spec?.thickness_mm ?? product.thickness_mm,
  };
  const swatch = decorSwatch(product.decor.decor_no, product.decor.decor_name, product.product_name, spec?.material_type);
  const reduced = useIsMotionReduced();
  const [orbit, setOrbit] = useState<OrbitState>(PRESETS.front);
  const [inView, setInView] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const captionId = useId();
  const dims = slabDimensions(measures);

  useEffect(() => {
    const element = stage.current;
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

  if (!swatch) {
    return (
      <PageSection title="Material" description="The decor on a slab of this product's real size.">
        <GlassPanel>
          <EmptyState
            icon="swatch"
            title="No preview for this decor yet"
            text="A preview needs a texture for the decor. It appears here once this decor has one."
            compact
          />
        </GlassPanel>
      </PageSection>
    );
  }

  const name = product.decor.decor_name ?? swatch.label;
  const label = `3D preview of ${name}`;
  const fmt = (value: string | null) => (value ? (formatDecimal(value, { locale, maxFractionDigits: 3 }) ?? value) : null);
  const sizeParts = [fmt(measures.length_mm), fmt(measures.width_mm), fmt(measures.thickness_mm)].filter((part): part is string => part !== null);
  const finish = product.finish ?? spec?.finish ?? null;
  const current = matchingPreset(orbit);
  // eslint-disable-next-line @next/next/no-img-element -- a decor texture built into the app, shown while WebGL loads
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
    <PageSection title="Material" description="The decor on a slab of this product's real size. A rendered preview, not a product photo.">
      <GlassPanel as="div" padding="none" className="overflow-hidden">
        <figure className="m-0 flex flex-col" aria-describedby={captionId}>
          <div
            ref={stage}
            role="group"
            aria-label={label}
            aria-roledescription="3D viewer"
            tabIndex={reduced ? -1 : 0}
            onKeyDown={onKeyDown}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            className={`relative aspect-[4/3] w-full overflow-hidden bg-sand-soft md:aspect-[16/9] ${reduced ? "" : "cursor-grab touch-none active:cursor-grabbing"}`}
            style={{ borderRadius: 0 }}
          >
            {inView ? (
              <LazyCanvas
                label={label}
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
          <div className="hairline-top flex flex-wrap items-center justify-between gap-4 px-5 py-4 md:px-6">
            <figcaption id={captionId} className="flex min-w-0 flex-col gap-1">
              <span className="t-label text-ink">
                {name}
                {product.decor.decor_no ? <span className="lk-mono text-ink-2"> · {product.decor.decor_no}</span> : null}
              </span>
              <span className="t-body-sm text-ink-2">
                {sizeParts.length > 0 ? <span className="lk-tnum">{sizeParts.join(" × ")} mm</span> : "Size not recorded"}
                {finish ? ` · ${finish}` : ""}
              </span>
            </figcaption>
            <SegmentedControl
              label="Viewing angle"
              size="sm"
              value={current ?? ""}
              onChange={(value) => {
                const preset = PRESET_OPTIONS.find((option) => option.value === value);
                if (preset) setOrbit(PRESETS[preset.value]);
              }}
              options={PRESET_OPTIONS}
            />
          </div>
        </figure>
      </GlassPanel>
      <p className="t-caption m-0 text-ink-3">
        {reduced ? "Pick an angle to look from." : "Drag the slab, or focus it and use the arrow keys, to turn it."} The texture is a stand-in for the decor family.
        {dims.complete ? "" : " Part of the size is missing, so a default slab is shown."}
      </p>
    </PageSection>
  );
}
