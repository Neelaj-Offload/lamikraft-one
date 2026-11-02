"use client";

import { MaterialPreview } from "@/features/material-viewer/material-preview";
import type { MaterialSubject } from "@/features/material-viewer/types";
import { productsMessages as m } from "@/messages/products";
import type { ProductDetail } from "./types";

/** Canonical specification millimetres first, the master size when the specification has none. */
export function materialSubjectOf(product: ProductDetail): MaterialSubject {
  const spec = product.specification;
  return {
    product_key: product.product_key,
    product_name: product.product_name,
    decor_no: product.decor.decor_no,
    decor_name: product.decor.decor_name,
    material_type: spec?.material_type ?? null,
    finish: product.finish ?? spec?.finish ?? null,
    length_mm: spec?.length_mm ?? product.size.length_mm,
    width_mm: spec?.width_mm ?? product.size.width_mm,
    thickness_mm: spec?.thickness_mm ?? product.thickness_mm,
  };
}

export function ProductMaterial({ product }: { product: ProductDetail }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-ink-muted">{m.detail.material.intro}</p>
      <MaterialPreview subject={materialSubjectOf(product)} className="max-w-2xl" />
    </div>
  );
}
