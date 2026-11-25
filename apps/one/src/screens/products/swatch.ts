/**
 * Decor swatches for the catalogue and the material view.
 *
 * The four fixture textures live in the old app's `public/swatches`, which this app does not
 * serve. They are imported as build assets here, so they ship with this app under hashed URLs.
 * Which decor gets which texture is still decided by the old `swatchForDecor`, the one place to
 * change when products carry their own decor renditions.
 */

import { swatchForDecor, type Swatch, type SwatchId } from "@/features/material-viewer/swatches";
import ashNormal from "../../../../web/public/swatches/ash-normal.webp";
import ashThumb from "../../../../web/public/swatches/ash-thumb.webp";
import ash from "../../../../web/public/swatches/ash.webp";
import mapleNormal from "../../../../web/public/swatches/maple-normal.webp";
import mapleThumb from "../../../../web/public/swatches/maple-thumb.webp";
import maple from "../../../../web/public/swatches/maple.webp";
import oakNormal from "../../../../web/public/swatches/oak-normal.webp";
import oakThumb from "../../../../web/public/swatches/oak-thumb.webp";
import oak from "../../../../web/public/swatches/oak.webp";
import walnutNormal from "../../../../web/public/swatches/walnut-normal.webp";
import walnutThumb from "../../../../web/public/swatches/walnut-thumb.webp";
import walnut from "../../../../web/public/swatches/walnut.webp";

const ASSETS: Record<SwatchId, { albedo: string; normal: string; thumb: string }> = {
  oak: { albedo: oak.src, normal: oakNormal.src, thumb: oakThumb.src },
  maple: { albedo: maple.src, normal: mapleNormal.src, thumb: mapleThumb.src },
  ash: { albedo: ash.src, normal: ashNormal.src, thumb: ashThumb.src },
  walnut: { albedo: walnut.src, normal: walnutNormal.src, thumb: walnutThumb.src },
};

/**
 * The swatch for a product: by decor number first, then by a species word in the names. Null
 * when nothing matches, so screens show no imagery rather than the wrong wood.
 */
export function decorSwatch(decorNo: string | null | undefined, ...names: ReadonlyArray<string | null | undefined>): Swatch | null {
  const match = swatchForDecor(decorNo, ...names);
  return match ? { ...match, ...ASSETS[match.id] } : null;
}
