#!/usr/bin/env python3
"""Generate the favicon set and the Open Graph share image for the Fifty
docs site. Both are derivatives of the canonical magazine-cover design
system (docs/assets/style.css + docs/favicon.svg), so the only sources of
truth a human edits are the SVG mark and the OG HTML template embedded
below — every binary file under docs/ that ships brand imagery is
regenerated from those two by this script.

What it writes (idempotent — overwrites on every run):

    docs/favicon-16.png         16x16 raster of the favicon mark
    docs/favicon-32.png         32x32 raster of the favicon mark
    docs/apple-touch-icon.png   180x180 raster of the favicon mark (iOS home)
    docs/favicon.ico            multi-size 16+32 ICO bundle for legacy
                                browsers / Windows pinned-site behaviour
    docs/assets/og-default.png  1200x630 Open Graph share card

Two render pipelines, picked per-asset:

  * Favicons → Pillow + a locally available serif (Bodoni 72 by default,
    Georgia fallback). Chrome rasterization of the SVG was unreliable at
    16x16 because Chrome can't fetch Google Fonts inside a `file://`
    SVG fast enough for the screenshot snapshot, and any miss collapses
    the `<text>` glyph to zero width — the favicon ended up as just the
    cobalt accent square with no "f" at all. Pillow with a guaranteed-
    present system serif sidesteps that whole class of failure.

  * OG image → headless Chrome, because the share card depends on DM
    Serif Display + IBM Plex Mono (Google Fonts) at large sizes where
    the substitution would visibly drift from the live site. At 1200px
    Chrome has time to fetch + render the webfonts before the
    --virtual-time-budget snapshot.

The on-disk SVG (docs/favicon.svg) remains the canonical mark — modern
browsers are served it directly via `<link rel="icon" type="image/svg+xml">`
so they get the real DM Serif Display rendering. The PNG/ICO derivatives
are an intentional, lower-fidelity fallback for the (shrinking) set of
clients that don't accept SVG icons.

Pipeline order (run by hand or via `make brand-assets`):

    1. python3 bin/build-brand-assets.py   ← this script
    2. python3 bin/build-redirects.py      (preserves the assets above)
    3. python3 bin/build-snap-gallery.py   (preserves docs/snaps/assets/)

Steps 2 and 3 explicitly preserve every file produced here across their
own destructive rebuilds (see the preservation block in build-redirects).

Usage:
    python3 bin/build-brand-assets.py
    python3 bin/build-brand-assets.py --check   # exit non-zero if anything
                                                # would change (CI gate)
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-only imports: lets mypy resolve the Pillow annotations on
    # `_load_serif` / `_draw_favicon` without forcing a real Pillow
    # install at runtime. Pillow is loaded lazily via `_require_pillow`
    # inside the rendering functions instead — see the docstring there
    # for the rationale (stdlib-only `bin/` convention).
    from PIL import Image, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SVG_MASTER = DOCS / "favicon.svg"


def _require_pillow() -> tuple:
    """Lazy import for Pillow. The repo's convention (per
    `requirements-dev.txt`) is that everything under `bin/` is stdlib-only
    so a fresh `python3 bin/<script>.py --help` works on a vanilla install.
    Pillow is the one external dep this script genuinely needs (for PNG /
    ICO encoding + image cropping), so we defer the import until the
    moment a render is actually about to happen — that way `--help` and
    `--check` argparse wiring stays usable without Pillow installed, and
    the CI smoke gate (which only invokes `--help`) doesn't need to
    install anything extra. The .ico assembly relies on Image.save's
    native multi-size support which landed in Pillow 7+."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print(
            "ERROR: Pillow is required to render brand assets.\n"
            "       pip install Pillow",
            file=sys.stderr,
        )
        sys.exit(2)
    return Image, ImageDraw, ImageFont


def _find_chrome() -> str:
    """Locate a headless-capable Chrome/Chromium. Mirrors the resolution
    order used by bin/snap.py so the two scripts stay portable in
    lockstep — if your machine can shoot a snap, it can render a
    favicon."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    print(
        "ERROR: no Chrome/Chromium binary found. Install Google Chrome or "
        "set FIFTY_CHROME to the executable path.",
        file=sys.stderr,
    )
    sys.exit(2)


def _chrome_screenshot(html_path: Path, out_png: Path, width: int, height: int) -> None:
    """Drive headless Chrome to render `html_path` at the exact pixel
    dimensions and dump the result to `out_png`. `--virtual-time-budget`
    gives Google Fonts up to 12s to fetch + paint before the screenshot
    fires — undershooting that produces fallback-serif renders that look
    nothing like the live site, and (more importantly) misses any text
    block sized in `em` since the fallback metrics differ from DM
    Serif's, collapsing or expanding entire layout sections."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    chrome = _find_chrome()
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            "--virtual-time-budget=12000",
            "--run-all-compositor-stages-before-draw",
            f"--screenshot={out_png}",
            html_path.as_uri(),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not out_png.is_file():
        raise RuntimeError(f"Chrome failed to write {out_png}")


# Magazine-cover palette — kept verbatim in sync with docs/assets/style.css
# so a change to either file alongside a re-run of this script is enough
# to roll the whole brand surface to a new colour.
PAPER = (255, 255, 255, 255)
INK = (0, 0, 0, 255)
ACCENT = (31, 79, 224, 255)  # #1f4fe0


# Candidate font paths probed in order. Bodoni 72 ships with macOS and is
# the closest local cousin to DM Serif Display (high-contrast didone with
# a similar lowercase-f silhouette). Bitstream / DejaVu Serif are common
# Linux fallbacks. Georgia rounds out the list as a last resort that is
# present on essentially every Mac and most Windows installs that
# happen to find their way onto a CI runner.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Bodoni 72.ttc",
    "/System/Library/Fonts/Supplemental/Bodoni 72 OS.ttc",
    "/Library/Fonts/Bodoni 72.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf",
    "/Library/Fonts/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]


def _load_serif(size: int) -> ImageFont.FreeTypeFont:
    """Return the highest-priority installed serif at the requested
    pixel size. Raises if no candidate resolves — that is a setup error
    worth surfacing rather than silently rendering a default sans."""
    _, _, ImageFont = _require_pillow()
    for path in _FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise RuntimeError(
        "No usable serif font found on this machine. Install one of: "
        + ", ".join(Path(p).name for p in _FONT_CANDIDATES)
    )


def _draw_favicon(size: int) -> Image.Image:
    """Draw the favicon mark at `size` x `size`. The mark is the brand's
    smallest legible distillation: white paper, a serif lowercase 'f' in
    pure black, with the cobalt period rendered as a solid square in the
    bottom-right (a square instead of a circle so it reliably survives
    the 16x16 bake without rounding into a single grey antialiased pixel)."""
    Image, ImageDraw, _ = _require_pillow()
    im = Image.new("RGBA", (size, size), PAPER)
    draw = ImageDraw.Draw(im)

    # Empirically-tuned sizing. The "f" sits left of center; the cobalt
    # square hugs the bottom-right corner. These ratios were tested at
    # 16, 32, and 180 and produce visually balanced marks at all three.
    f_size = round(size * 0.95)
    accent_size = max(2, round(size * 0.22))
    accent_pad = max(1, round(size * 0.10))
    f_x = max(1, round(size * 0.18))
    # Vertical baseline: pull "f" down so its top serif aligns with the
    # top of the cell. We render via anchor="ls" (left baseline) which
    # makes the math straightforward — we just need to land the baseline
    # near the bottom of the visible character.
    f_baseline_y = round(size * 0.86)

    font = _load_serif(f_size)
    draw.text((f_x, f_baseline_y), "f", fill=INK, font=font, anchor="ls")

    # Cobalt square in the bottom-right corner.
    ax1 = size - accent_pad
    ay1 = size - accent_pad
    ax0 = ax1 - accent_size
    ay0 = ay1 - accent_size
    draw.rectangle((ax0, ay0, ax1, ay1), fill=ACCENT)
    return im


def _build_favicons(*, dry_run: bool) -> list[Path]:
    """Render the favicon mark to every PNG variant + bundle the small
    sizes into a multi-size .ico. Returns the list of files that were
    written (used by the --check gate to diff against the committed copy)."""
    if not SVG_MASTER.is_file():
        print(
            f"ERROR: {SVG_MASTER.relative_to(ROOT)} missing — modern "
            "browsers serve the SVG directly; the rasterized PNG/ICO files "
            "below are derivatives, not stand-ins.",
            file=sys.stderr,
        )
        sys.exit(2)

    targets = {
        16: DOCS / "favicon-16.png",
        32: DOCS / "favicon-32.png",
        180: DOCS / "apple-touch-icon.png",
    }
    written: list[Path] = []
    # `Any` rather than `Image.Image` so the dict annotation evaluates
    # cleanly when Pillow isn't installed (it isn't on the CI smoke
    # runner — Pillow is only needed for the actual render path).
    rendered_pngs: dict[int, Any] = {}
    for size, dst in targets.items():
        im = _draw_favicon(size)
        rendered_pngs[size] = im
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.save(dst, format="PNG", optimize=True)
        written.append(dst)
        print(f"  rendered {dst.relative_to(ROOT)} ({size}x{size})")

    # Multi-size ICO bundle: browsers + the Windows shell pick whichever
    # frame matches the surface (tab favicon = 16, taskbar = 32). 180px
    # belongs to apple-touch only and bloats the .ico unnecessarily, so
    # we exclude it.
    ico_dst = DOCS / "favicon.ico"
    if not dry_run:
        rendered_pngs[32].save(
            ico_dst,
            format="ICO",
            sizes=[(16, 16), (32, 32)],
        )
    written.append(ico_dst)
    print(f"  wrote    {ico_dst.relative_to(ROOT)} (16+32 multi-size)")
    return written


# Open Graph share card. Renders at 1200x630 (the FB/Twitter/LinkedIn
# canonical size) and looks like a magazine cover stripped to its loudest
# elements: tiny mono masthead, giant "fifty." with cobalt period, hairline
# rule, italic deck. Mirrors docs/index.html visually so the share preview
# and the landing page read as the same artifact.
OG_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<!-- <link> + preconnect, not @import inside <style>, because Chrome's
     headless screenshot pipeline races @import against the snapshot:
     even with --virtual-time-budget=12s the page can paint before the
     async stylesheet resolves, leaving entire flex children (the
     colophon was the casualty) at their pre-font intrinsic size and
     pushing them outside the 1200x630 capture frame. <link> blocks
     rendering on the stylesheet, so by the time Chrome paints anything
     the layout is already final. -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Serif+Text:ital@1&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  html, body { margin: 0; padding: 0; background: #ffffff; color: #000; }
  /* The card uses absolute positioning rather than flex so the masthead
     and colophon land at fixed pixel coordinates regardless of how
     long it takes the Google Fonts to fetch + paint. With flex layout
     the colophon was repeatedly getting clipped off the bottom of the
     630px capture frame whenever the headline text re-flowed at a
     larger size after webfont swap-in. Pinning every band to an
     explicit `top:` / `bottom:` makes the layout deterministic at
     screenshot time. */
  .card {
    position: relative;
    width: 1200px; height: 630px;
    box-sizing: border-box;
    background: #ffffff;
    font-family: 'DM Serif Text', Georgia, serif;
    font-style: italic;
  }
  .row {
    position: absolute; left: 56px; right: 56px;
    display: flex; justify-content: space-between; align-items: baseline;
    font-family: 'IBM Plex Mono', monospace; font-style: normal;
    font-size: 14px; letter-spacing: .12em; text-transform: uppercase;
  }
  .masthead { top: 32px; padding-bottom: 14px; border-bottom: 1.5px solid #000; }
  .colophon { bottom: 28px; padding-top: 14px; border-top: 1.5px solid #000; }
  .colophon .accent { color: #1f4fe0; }
  .body {
    position: absolute; left: 56px; right: 56px;
    top: 110px;  /* clears the masthead band */
    bottom: 110px;  /* clears the colophon band */
    display: flex; flex-direction: column; justify-content: center; gap: 14px;
  }
  /* 200px keeps the literal 'fifty.' tall enough to read as the headline
     element while leaving room for a two-line deck below within the
     400px-tall .body band. */
  .title {
    font-family: 'DM Serif Display', Georgia, serif; font-style: normal;
    font-size: 200px; line-height: .85; letter-spacing: -.045em;
    margin: 0;
  }
  .title .dot { color: #1f4fe0; }
  /* 28px keeps the longer manifesto deck (~22 words) inside two lines at
     1080px max-width without webfont reflow risk; the previous 30px
     overflowed to three lines after the README-voice rewrite. */
  .deck {
    font-size: 28px; line-height: 1.18; letter-spacing: -.005em;
    margin: 0; max-width: 1080px;
  }
</style>
</head>
<body>
<div class="card">
  <div class="row masthead">
    <span>An experiment for WooCommerce &middot; AI agents, on strict rails</span>
    <span>demo.regionallyfamous.com</span>
  </div>
  <div class="body">
    <h1 class="title">fifty<span class="dot">.</span></h1>
    <p class="deck">WooCommerce powers more stores than Shopify and ships nothing like Shopify&rsquo;s themes. Rich and I are closing that gap, in public.</p>
  </div>
  <div class="row colophon">
    <span>WordPress &middot; WooCommerce &middot; Playground</span>
    <span class="accent">github.com/RegionallyFamous/fifty</span>
  </div>
</div>
</body>
</html>
"""


def _build_og_card(*, dry_run: bool) -> Path:
    """Render the 1200x630 OG share image from the template above.
    Single canonical card for every page on the docs site (landing,
    concepts, snaps, redirectors). Per-page OG variants are deliberately
    out of scope until the share volume justifies the extra surface.

    Implementation note: we deliberately render Chrome at a viewport
    *taller* than the card (1200x900) and then crop the top 1200x630
    band out with Pillow. Asking Chrome for an exactly-content-sized
    viewport (1200x630) reliably clips any element that uses
    `position: absolute; bottom:` because Chrome's headless capture
    pipeline appears to compute the absolute-bottom offset against a
    viewport that is a few pixels shorter than the content (probably
    scrollbar gutter reservation), pushing the colophon into the
    cropped strip. Rendering tall + cropping eliminates that whole class
    of clipping bug."""
    Image, _, _ = _require_pillow()
    out = DOCS / "assets" / "og-default.png"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        html = tmp / "og.html"
        html.write_text(OG_TEMPLATE, encoding="utf-8")
        oversize = tmp / "og-oversize.png"
        _chrome_screenshot(html, oversize, 1200, 900)
        with Image.open(oversize) as raw:
            cropped = raw.crop((0, 0, 1200, 630))
            staged = tmp / "og-default.png"
            cropped.save(staged, format="PNG", optimize=True)
        if not dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staged, out)
    print(f"  rendered {out.relative_to(ROOT)} (1200x630 share card)")
    return out


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Render to a temp dir and exit non-zero if any output would differ from the committed copy. Used by CI to fail loudly when someone hand-edits a derivative without re-running the script.",
    )
    args = parser.parse_args(argv)

    print("Fifty brand assets — rendering from docs/favicon.svg + OG template")
    print(f"  Chrome:  {_find_chrome()}")
    print(f"  Master:  {SVG_MASTER.relative_to(ROOT)}")
    print()

    if args.check:
        # Snapshot existing digests, render into a temp dir, diff.
        existing: dict[Path, str | None] = {}
        for rel in [
            DOCS / "favicon-16.png",
            DOCS / "favicon-32.png",
            DOCS / "apple-touch-icon.png",
            DOCS / "favicon.ico",
            DOCS / "assets" / "og-default.png",
        ]:
            existing[rel] = _digest(rel) if rel.is_file() else None
        _build_favicons(dry_run=False)
        _build_og_card(dry_run=False)
        drifted: list[Path] = []
        for rel, before in existing.items():
            after = _digest(rel) if rel.is_file() else None
            if before != after:
                drifted.append(rel)
        if drifted:
            print()
            print("DRIFT: brand assets out of sync with sources:")
            for d in drifted:
                print(f"  - {d.relative_to(ROOT)}")
            print("Re-run `python3 bin/build-brand-assets.py` and commit the result.")
            return 1
        print()
        print("OK: every brand-asset binary is in sync with its source.")
        return 0

    _build_favicons(dry_run=False)
    _build_og_card(dry_run=False)
    print()
    print("Done. Re-run bin/build-redirects.py + bin/build-snap-gallery.py")
    print("to wire the new assets into every page's <head>.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
