import Image from "next/image";
import { cx } from "@/lib/cx";

/**
 * The Lamikraft logo: the wordmark with the board-and-leaf mark in the gap. Two files, one per
 * ground; CSS shows the right one for the active theme (explicit or system). Never recoloured.
 * Intrinsic sizes: light 270x75, dark 1480x570 (the dark file carries more padding).
 */
export function BrandLogo({ height = 40, className }: { height?: number; className?: string }) {
  return (
    <span className={cx("brand-logo", className)} role="img" aria-label="Lamikraft, designed to perform">
      <Image
        src="/brand/lamikraft-logo-light.webp"
        alt=""
        width={Math.round((height * 270) / 75)}
        height={height}
        className="brand-logo-light"
        priority
      />
      <Image
        src="/brand/lamikraft-logo-dark.webp"
        alt=""
        width={Math.round((height * 1.25 * 1480) / 570)}
        height={Math.round(height * 1.25)}
        className="brand-logo-dark"
        loading="lazy"
      />
    </span>
  );
}
