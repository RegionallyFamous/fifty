#!/usr/bin/env python3
"""Generate per-theme ``screenshot.png`` from the committed snap baselines.

Background:
  Every WordPress theme ships a ``screenshot.png`` that the admin Themes screen
  uses as the card image. The convention is 1200x900 (4:3). Before this script
  every theme in the monorepo had the SAME placeholder bytes copied into it
  (md5sum identical across obel/chonk/lysholm/selvedge/aero), so the admin
  screen showed five identical cards labelled with five different theme names.

  The snap framework already ships a real, full-page rendered home shot for
  every theme at::

    tests/visual-baseline/<theme>/desktop/home.png   (1280 x ~2800, full page)

  This script crops the top portion of that baseline (the part that contains
  the header, hero, and first row of featured products — i.e. the part you'd
  actually want as a theme card), resizes it to 1200x900 with high-quality
  resampling, and writes the result to ``<theme>/screenshot.png``.

  Wire-up:
  - Run manually after a snap baseline pass: ``python3 bin/build-theme-screenshots.py``
  - Or for a single theme: ``python3 bin/build-theme-screenshots.py obel``
  - Run as part of the rebaseline workflow described in
    docs/visual-snapshots.md (see also the wiki Visual-Snapshots page).
  - bin/check.py grows a ``check_theme_screenshots()`` gate that fails CI if
    any two themes' screenshot.png files share an md5 — same-bytes is the
    regression we're preventing.

Why crop+resize rather than a fresh render?
  The full snap framework already does the hard work of booting Playground +
  WooCommerce + the seeded W&O catalogue and producing a deterministic shot.
  Rendering AGAIN here would (a) double the runtime, (b) introduce drift from
  the visual baseline reviewers approve, and (c) duplicate the Playground +
  Playwright plumbing for no benefit. Cropping the existing baseline keeps the
  admin card guaranteed-consistent with what we ship in tests/visual-baseline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _lib import MONOREPO_ROOT, iter_themes, resolve_theme_root

# WordPress's documented screenshot.png convention. The admin Themes grid renders
# cards at 387x290 (4:3), so anything above ~387px wide is sharp on hidpi; the
# WordPress.org theme directory uses 1200x900 as the canonical upload size.
TARGET_W = 1200
TARGET_H = 900

# Where to look for the source full-page home shot, in priority order:
#   1. The committed baseline (reviewer-approved, deterministic across CI).
#   2. The latest fresh snap in tmp/snaps/ (so you can build a screenshot for
#      a brand-new theme that has never been baselined yet).
# Each path uses the same desktop viewport (1280 wide, full-page tall ~2800)
# because the desktop crop has the right aspect for the WP admin card —
# mobile crops the hero awkwardly and wide letterboxes too much.
SOURCE_PATH_CANDIDATES = (
    Path("tests/visual-baseline") / "{theme}" / "desktop" / "home.png",
    Path("tmp/snaps") / "{theme}" / "desktop" / "home.png",
)


def _resolve_source(theme_slug: str) -> Path:
    """Return the first existing full-page home shot for ``theme_slug``."""
    for candidate in SOURCE_PATH_CANDIDATES:
        path = MONOREPO_ROOT / candidate.as_posix().format(theme=theme_slug)
        if path.exists():
            return path
    raise FileNotFoundError(
        f"no home shot for {theme_slug}. "
        f"Run `python3 bin/snap.py shoot {theme_slug} --routes home` to "
        f"generate tmp/snaps/{theme_slug}/desktop/home.png, then re-run."
    )


def _build_one(theme_dir: Path) -> Path:
    """Crop + resize the home baseline into ``<theme_dir>/screenshot.png``.

    Returns the screenshot path on success. Raises FileNotFoundError if the
    theme has neither a committed baseline nor a fresh snap to read from.
    """
    source = _resolve_source(theme_dir.name)

    # Pillow is a heavy optional dep. Importing lazily keeps the rest of
    # the script (argparse `--help`, theme discovery) usable in CI/dev
    # environments that don't install Pillow — only the actual crop step
    # requires it.
    from PIL import Image

    with Image.open(source) as src:
        src = src.convert("RGB")  # screenshot.png is RGB, drop alpha
        sw, sh = src.size

        # Crop a 4:3 region starting from the very top (y=0) so the header +
        # hero land in the card. Width matches the source so we never up-scale
        # horizontally — only the (always-shorter) crop height is computed.
        crop_h = round(sw * TARGET_H / TARGET_W)
        if crop_h > sh:
            # Source baseline shorter than 4:3 of its width — extremely
            # unlikely for full-page snaps but handled rather than crashing.
            crop_h = sh
        crop = src.crop((0, 0, sw, crop_h))

        # Down-sample to the WP-standard 1200x900 with LANCZOS so text edges
        # stay crisp on the admin card.
        out = crop.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)

        dest = theme_dir / "screenshot.png"
        out.save(dest, format="PNG", optimize=True)
        # Print the source so failures (or "why is this card the wrong page?")
        # can be traced back to exactly which snap fed which screenshot.
        print(f"    source: {source.relative_to(MONOREPO_ROOT)}")
        return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "theme",
        nargs="?",
        help="Theme slug (omit to run for every theme in the monorepo).",
    )
    args = parser.parse_args()

    if args.theme:
        targets = [resolve_theme_root(args.theme)]
    else:
        targets = list(iter_themes())

    failures = 0
    for theme_dir in targets:
        try:
            dest = _build_one(theme_dir)
        except FileNotFoundError as e:
            print(f"  - {theme_dir.name}: SKIP — {e}")
            failures += 1
            continue
        size_kb = dest.stat().st_size / 1024
        print(f"  + {theme_dir.name}: wrote {dest.relative_to(MONOREPO_ROOT)} ({size_kb:,.0f} KB)")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
