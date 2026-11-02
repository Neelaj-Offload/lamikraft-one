"""Generate the illustrative fixture swatches in public/swatches/ (Pillow only, deterministic).

The repository has no product media yet (catalogue media lands in Slice 2). Until then the material
viewer and the sign-in composition use four procedural wood swatches, one per fixture decor:
natural oak (0120), hard maple (0310), white ash (0415) and American walnut (0457). Each species
gets an albedo map, a tangent-space normal map derived from the same height field, and a 160 px
thumbnail. Re-run from apps/web: `../../backend/.venv/Scripts/python scripts/gen-swatches.py`.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps

SIZE = 1024
LOW = 384  # the ring phase is computed in Python at this size and upscaled
OUT = Path(__file__).resolve().parent.parent / "public" / "swatches"


class ValueNoise:
    """Smooth 2D value noise from a seeded lattice (bilinear, smoothstep), three octaves."""

    def __init__(self, seed: int, cells: int = 64) -> None:
        rng = random.Random(seed)
        self.cells = cells
        self.lattice = [[rng.random() for _ in range(cells + 1)] for _ in range(cells + 1)]

    def _at(self, x: float, y: float) -> float:
        cells = self.cells
        x %= cells
        y %= cells
        x0 = int(x)
        y0 = int(y)
        fx = x - x0
        fy = y - y0
        fx = fx * fx * (3 - 2 * fx)
        fy = fy * fy * (3 - 2 * fy)
        x1 = (x0 + 1) % cells
        y1 = (y0 + 1) % cells
        row0 = self.lattice[y0]
        row1 = self.lattice[y1]
        top = row0[x0] + (row0[x1] - row0[x0]) * fx
        bottom = row1[x0] + (row1[x1] - row1[x0]) * fx
        return top + (bottom - top) * fy

    def octaves(self, x: float, y: float) -> float:
        """-1..1, three octaves."""
        v = self._at(x, y) * 0.62 + self._at(x * 2.1 + 7.3, y * 2.1 + 3.1) * 0.26 + self._at(x * 4.3 + 1.7, y * 4.3 + 9.2) * 0.12
        return v * 2 - 1


def ring_value(phase: float, contrast: float) -> float:
    """Earlywood wide and pale, latewood narrow and dark: a cosine raised to a power, 0..1 darkness."""
    v = 0.5 * (1 + math.cos(2 * math.pi * phase))
    return contrast * v**4


def ring_field(rings: float, contrast: float, seed: int) -> Image.Image:
    """Growth rings along x at LOW resolution: ring width varies slowly (thick summers, thin winters),
    the rings drift and arch like a flat-sawn board, and a fine wobble breaks the straight lines."""
    drift = ValueNoise(seed)
    width = ValueNoise(seed + 1)
    wobble = ValueNoise(seed + 2)
    pixels = bytearray(LOW * LOW)
    # Ring spacing modulated along y: integrate a slowly varying frequency so widths change smoothly.
    freq_along_y = [rings / LOW * (1 + 0.55 * width.octaves(3.0, y / LOW * 5.0)) for y in range(LOW)]
    cumulative = [0.0]
    for y in range(1, LOW):
        cumulative.append(cumulative[-1] + freq_along_y[y])
    for y in range(LOW):
        ny = y / LOW
        base = cumulative[y]
        row = y * LOW
        for x in range(LOW):
            nx = x / LOW
            # Large drift bends the rings into arches; small wobble roughens each line.
            phase = base + 2.4 * drift.octaves(nx * 1.3, ny * 1.3) + 0.07 * wobble.octaves(nx * 18, ny * 18)
            pixels[row + x] = int(255 - 255 * ring_value(phase, contrast))
    return Image.frombytes("L", (LOW, LOW), bytes(pixels)).resize((SIZE, SIZE), Image.Resampling.BICUBIC)


def streaks(height: int, sigma: float, seed: int, resample=Image.Resampling.BILINEAR) -> Image.Image:
    random.seed(seed)
    return Image.effect_noise((SIZE, height), sigma).resize((SIZE, SIZE), resample)


def height_field(rings: float, contrast: float, pores: float, seed: int) -> Image.Image:
    band = ring_field(rings, contrast, seed)
    fibre = streaks(48, 46, seed + 3).filter(ImageFilter.GaussianBlur(0.7))
    pore = streaks(SIZE // 5, 24, seed + 4, Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(0.5))
    field = Image.blend(band, fibre, 0.18)
    field = Image.blend(field, pore, pores * 0.45)
    return ImageOps.autocontrast(field, cutoff=0.5)


def normal_map(height: Image.Image, strength: float) -> Image.Image:
    # Sobel on a slightly smoothed height; the band structure dominates, pores add fine relief.
    smooth = height.filter(ImageFilter.GaussianBlur(1.2))
    sx = ImageFilter.Kernel((3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1 / strength, offset=128)
    sy = ImageFilter.Kernel((3, 3), [1, 2, 1, 0, 0, 0, -1, -2, -1], scale=1 / strength, offset=128)
    dx = ImageChops.invert(smooth.filter(sx))
    dy = smooth.filter(sy)
    blue = Image.new("L", (SIZE, SIZE), 236)
    return Image.merge("RGB", (dx, dy, blue))


# (shadow, mid, highlight) sRGB; rings across the swatch; ring contrast; pore strength; seed
SPECIES = {
    "oak": ((88, 58, 30), (184, 136, 86), (226, 194, 146), 26, 0.62, 0.30, 11),
    "maple": ((166, 130, 86), (226, 202, 160), (247, 234, 206), 18, 0.24, 0.08, 23),
    "ash": ((140, 106, 66), (208, 184, 140), (242, 228, 198), 22, 0.42, 0.14, 37),
    "walnut": ((38, 22, 14), (98, 62, 42), (158, 116, 84), 30, 0.58, 0.20, 53),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (shadow, mid, light, rings, contrast, pores, seed) in SPECIES.items():
        field = height_field(rings, contrast, pores, seed)
        albedo = ImageOps.colorize(field, black=shadow, white=light, mid=mid, midpoint=128)
        albedo.save(OUT / f"{name}.webp", "WEBP", quality=84, method=6)
        normal_map(field, 3.2).save(OUT / f"{name}-normal.webp", "WEBP", quality=88, method=6)
        albedo.resize((160, 160), Image.Resampling.LANCZOS).save(OUT / f"{name}-thumb.webp", "WEBP", quality=80, method=6)
        print(name, "ok")


if __name__ == "__main__":
    main()
