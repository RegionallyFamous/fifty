#!/usr/bin/env python3
"""Extract a 5-color dominant palette from each concept mockup.

Output: a hex array like ``["#f4ecd8", "#5a1f1a", "#1a1a1a", "#7c5b34",
"#cba56b"]`` per slug, ordered by descending pixel-share so the first
entry is the dominant background and later entries are accents.

Algorithm: simple bucket-quantization in HSV space.

* Pillow loads the image and aggressively downsamples (max 240×240) so
  the rest of the pipeline runs on ~50k pixels max — at full resolution
  a 1024×580 mockup would be ~600k pixels, and we'd be doing this for
  102 of them on every CI run.
* Each pixel is bucketed into a 12 × 8 × 8 (H × S × V) grid. The grid
  is coarser than k-means but completely deterministic, has no random
  init to seed, and runs in pure stdlib + Pillow — no scikit-learn,
  no numpy. Output is byte-stable across runs and across machines.
* The top-N populated buckets become the palette; we map each bucket
  back to the *median* RGB of the pixels that fell into it (not the
  bucket centre) so the colors look like the mockup, not like crayon.
* Pixels with very low alpha are skipped, and pure-white / pure-black
  pixels above a per-image saturation gate are deprioritised so a
  page with a giant white background doesn't drown out the brand
  accents that actually identify the concept.

This script is dev-only — it runs under requirements-dev.txt's Pillow
and is invoked by ``bin/build-concept-meta.py`` and the test suite.
The runtime gallery rendering in ``bin/build-redirects.py`` reads only
the resulting JSON, never the PNG, so the prod path stays stdlib-only.

Usage:
    python3 bin/extract-palette.py mockups/mockup-cobbler.png
    python3 bin/extract-palette.py mockups/cobbler/home.png --count 5
"""

from __future__ import annotations

import argparse
import colorsys
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import cast

# Pillow is in requirements-dev.txt; if it's missing, we fail fast with
# a helpful pointer rather than crashing on the import.
try:
    from PIL import Image
except ImportError:
    print(
        "ERROR: bin/extract-palette.py needs Pillow. "
        "Run `pip install -r requirements-dev.txt` (or `pip install Pillow`)",
        file=sys.stderr,
    )
    raise

MAX_DIM = 240
DEFAULT_COUNT = 5

# HSV bucket grid. 12 hue bands ~= every 30° (red, orange, yellow, …)
# which is loose enough that an "ember orange" and a "rust" land in the
# same bucket (good — they're the same color family for our purposes)
# but a "scarlet" and a "magenta" stay separate. 8 saturation x 8 value
# levels keep grey ramps distinct from saturated paints.
HUE_BUCKETS = 12
SAT_BUCKETS = 8
VAL_BUCKETS = 8


def _bucket(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    # Greys collapse all hues into bucket 0 so we don't fragment
    # white/black across 12 hue bins.
    if s < 0.05:
        h_idx = 0
    else:
        h_idx = min(int(h * HUE_BUCKETS), HUE_BUCKETS - 1)
    s_idx = min(int(s * SAT_BUCKETS), SAT_BUCKETS - 1)
    v_idx = min(int(v * VAL_BUCKETS), VAL_BUCKETS - 1)
    return (h_idx, s_idx, v_idx)


def _bucket_weight(s_idx: int, v_idx: int) -> float:
    """Strong bias toward saturated pixels.

    Naïve pixel-count ranking puts the giant white background at #1
    on every mockup; the actual brand accents (a lime CRT glow on
    cathode, a vermilion stamp on sable) get drowned out. The
    saturation_factor ramps from 0.15 at desaturated to 1.0 at fully
    saturated — high enough to push small saturated regions ahead of
    huge near-white plateaus, low enough that a generally-pale concept
    (lustre, halcyon) still keeps its cream as one of the five colors.
    """
    sat_norm = s_idx / (SAT_BUCKETS - 1)
    val_norm = v_idx / (VAL_BUCKETS - 1)
    saturation_factor = 0.15 + 0.85 * sat_norm
    value_factor = 0.4 + 0.6 * val_norm
    return saturation_factor * value_factor


def extract_palette(image_path: Path, count: int = DEFAULT_COUNT) -> list[str]:
    """Return ``count`` hex strings sorted by descending importance."""
    img = Image.open(image_path).convert("RGBA")
    img.thumbnail((MAX_DIM, MAX_DIM))
    pixels = img.load()
    if pixels is None:
        return []
    w, h = img.size
    # Map bucket -> [(r, g, b), ...] so we can median-collapse later.
    buckets: dict[tuple[int, int, int], list[tuple[int, int, int]]] = defaultdict(list)
    bucket_weights: dict[tuple[int, int, int], float] = defaultdict(float)
    for y in range(h):
        for x in range(w):
            # Pillow's PixelAccess returns a tuple, but its declared type
            # is `float | tuple[int, ...]` (PixelAccess is generic over the
            # image's mode). We forced .convert("RGBA") above, so it's
            # always a 4-tuple — `cast` keeps mypy happy without runtime
            # cost.
            pixel = cast(tuple[int, int, int, int], pixels[x, y])
            r, g, b, a = pixel
            if a < 128:
                continue
            key = _bucket((r, g, b))
            buckets[key].append((r, g, b))
            bucket_weights[key] += _bucket_weight(key[1], key[2])
    if not buckets:
        return []
    # Rank buckets by weighted population, then peel off the top
    # `count` *visually distinct* buckets. Two buckets are "the same
    # color" when their median RGBs are within MIN_DIST in Euclidean
    # space — without this dedupe a mockup with five shades of near-
    # black (cursor, neon at full strength) returns five near-identical
    # blacks instead of black + the magenta/lime accents.
    MIN_DIST = 60  # ~ a quarter of the RGB diagonal; eyeballed to match perceptual difference
    ranked = sorted(buckets.keys(), key=lambda k: bucket_weights[k], reverse=True)
    palette: list[str] = []
    chosen: list[tuple[int, int, int]] = []
    for key in ranked:
        members = buckets[key]
        rep = (
            int(median(p[0] for p in members)),
            int(median(p[1] for p in members)),
            int(median(p[2] for p in members)),
        )
        if any(
            ((rep[0] - c[0]) ** 2 + (rep[1] - c[1]) ** 2 + (rep[2] - c[2]) ** 2) ** 0.5 < MIN_DIST
            for c in chosen
        ):
            continue
        chosen.append(rep)
        palette.append("#{:02x}{:02x}{:02x}".format(*rep))
        if len(palette) >= count:
            break
    return palette


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a dominant palette from a mockup PNG.")
    parser.add_argument("image", type=Path, help="Path to a PNG mockup")
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"How many colors to return (default {DEFAULT_COUNT})",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit a JSON array instead of one hex per line"
    )
    args = parser.parse_args()

    if not args.image.is_file():
        print(f"ERROR: {args.image} is not a file", file=sys.stderr)
        return 2
    palette = extract_palette(args.image, count=args.count)
    if args.json:
        print(json.dumps(palette))
    else:
        for hex_color in palette:
            print(hex_color)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
