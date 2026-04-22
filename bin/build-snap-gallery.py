#!/usr/bin/env python3
"""Generate `docs/snaps/` — a static HTML gallery of every snap PNG so you
can scan each theme's surfaces at a glance without booting Playground.

Why this exists:
  `bin/snap.py shoot` writes 65 PNGs per theme (12 routes × 4 viewports +
  5 interaction frames) into `tmp/snaps/<theme>/`. That tree is gitignored
  and `bin/snap.py report` only emits Markdown + JSON rollups; there is no
  way to eyeball "is the lysholm front page actually painting an image?"
  short of opening each `.png` by hand or booting the Playground at
  https://demo.regionallyfamous.com/lysholm/. This script bridges the gap:
  it picks the freshest source on disk (tmp first, baseline fallback),
  re-encodes each PNG as a 600px-wide ~50KB progressive JPEG, and emits
  a per-theme HTML grid + a top-level theme picker into `docs/snaps/`.
  Result is served by the existing GitHub Pages deployment (branch=main,
  folder=/docs) at https://demo.regionallyfamous.com/snaps/.

Source resolution (per theme):
  1. `tmp/snaps/<theme>/manifest.json` — preferred. Built by `bin/snap.py
     shoot`; covers every cell including interaction frames, with
     `error_count` / `warn_count` pulled straight from the matching
     `.findings.json` (post-suppression, what reviewers actually see).
  2. `tests/visual-baseline/<theme>/<viewport>/<slug>.png` — fallback for
     themes/viewports that haven't been re-shot locally. No interactions,
     no findings counts (baseline tree is just PNGs).

Output layout (matches snap.py's tmp/snaps layout so the URL of every
gallery cell is structurally identical to its on-disk PNG):
  docs/snaps/
    index.html                                 # theme picker
    assets/style.css                           # shared styling
    <theme>/
      index.html                               # per-theme grid
      <viewport>/
        <slug>.jpg                             # 600px wide JPEG

Sort order: themes follow `snap_config.THEME_ORDER`; viewports follow
`snap_config.VIEWPORTS`; routes follow `snap_config.ROUTES`. Interaction
frames appear directly below their parent route, sorted by interaction
name. This matches every other snap-derived report so a cross-reference
between (e.g.) `bin/snap.py report` output and the gallery grid lands on
the same cell every time.

Usage:
  python3 bin/build-snap-gallery.py                # every theme, auto source
  python3 bin/build-snap-gallery.py --theme lysholm
  python3 bin/build-snap-gallery.py --source baseline   # force baseline tree
  python3 bin/build-snap-gallery.py --source tmp        # require tmp/snaps
  python3 bin/build-snap-gallery.py --clean             # ignore mtime cache

Performance:
  Re-encoding 325 PNGs through Pillow takes ~12s on an M1; subsequent
  runs are near-instant because each output JPEG is mtime-skipped against
  its source PNG. `--clean` forces a full re-encode (use after changing
  the JPEG quality knobs in this file).

Out of scope:
  This script does NOT shoot anything. It only re-encodes whatever PNGs
  are already on disk. Run `python3 bin/snap.py shoot --all` first if you
  want fresh imagery.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from snap_config import INTERACTIONS, ROUTES, THEME_ORDER, VIEWPORTS  # noqa: E402


def _require_pillow():
    """Lazy import of Pillow so `--help` (and import-only smoke tests in
    CI's `tools` job, which doesn't install requirements-dev) don't trip
    over a missing optional dep. Real work paths call this and exit
    cleanly if Pillow isn't there."""
    try:
        from PIL import Image
    except ImportError:
        print(
            "ERROR: Pillow is required. Install with `pip install Pillow` "
            "(it's already in `requirements-dev.txt`).",
            file=sys.stderr,
        )
        sys.exit(2)
    return Image

# Re-encoding knobs. 600px wide is the smallest size where the desktop
# checkout layout is still legible at thumbnail scale; q=80 hits the
# bytes-per-cell sweet spot (~50-100KB per JPEG; full gallery commit
# ~25MB across all 5 themes). Bump WIDTH_PX if you need finer detail
# (every theme's pixel-perfect spacing audit will want 1024 instead).
THUMB_WIDTH_PX = 600
THUMB_MAX_HEIGHT_PX = 4000  # cap full-page screenshots so Pillow doesn't OOM
JPEG_QUALITY = 80

# The top-level snap picker (docs/snaps/index.html) renders each theme as a
# magazine-spread card whose hero shot occupies ~60% of a ~1100px content
# column — i.e. ~660px wide and, on retina, ~1320px effective. Reusing the
# 600px gallery thumbnail there means a 2x upscale that visibly softens
# every type edge, so we encode a *separate* hero crop at the source PNG's
# native width and crop it to a wide 16:10 frame from the top of the page
# (matching the CSS object-position). 5 themes × ~250-400KB per file is a
# ~2MB budget hit on the gallery commit — well worth the sharpness gain.
HERO_WIDTH_PX = 1280  # native desktop snap width; never upscale
HERO_ASPECT = (16, 10)
HERO_QUALITY = 88

DOCS_SNAPS = ROOT / "docs" / "snaps"
TMP_SNAPS = ROOT / "tmp" / "snaps"
BASELINE = ROOT / "tests" / "visual-baseline"

VIEWPORT_ORDER = [v.name for v in VIEWPORTS]
ROUTE_ORDER = [r.slug for r in ROUTES]
ROUTE_BY_SLUG = {r.slug: r for r in ROUTES}

# Per-theme blurb. Mirrors `docs/index.html`'s wording so the gallery and
# the Playground launcher stay aligned. Keep these in sync if you touch
# the landing page.
THEME_BLURBS: dict[str, str] = {
    "obel": "Editorial: hairline borders, generous whitespace, warm cream palette.",
    "chonk": "Neo-brutalist: cream + 4px black borders, hard offset shadows, no rounded corners. For shops that want to be loud on purpose.",
    "selvedge": "Workwear-heritage: warm dark palette, italic display serif, small-batch maker's voice.",
    "lysholm": "Nordic home goods: pale cream, soft tan accents, unhurried serif typography.",
    "aero": "Y2K iridescent: holographic pastels, glassy chrome buttons, sparkle product cards.",
}


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------


class Cell(NamedTuple):
    """One thing the gallery shows: a single PNG capture for a (theme,
    viewport, route-or-route.flow) tuple, plus whatever per-cell metadata
    the source manifest carried about it.

    NamedTuple (not @dataclass) to match the rest of bin/snap_config.py
    and to stay importable under Python 3.9's `spec_from_file_location`
    smoke test, which can't resolve `from __future__ import annotations`
    string hints during dataclass field construction.
    """

    theme: str
    viewport: str
    slug: str
    base_route: str
    interaction: str | None
    src_png: Path
    error_count: int | None
    warn_count: int | None
    # Per-finding evidence crops captured by `bin/snap.py` next to the
    # full PNG. Each entry is (severity, kind, message, src_jpg_path).
    # `src_jpg_path` is repo-relative; build() copies it into the gallery
    # output dir alongside the cell thumbnail.
    crops: tuple[tuple[str, str, str, str], ...] = ()

    @property
    def is_interaction(self) -> bool:
        return self.interaction is not None

    @property
    def thumb_rel(self) -> str:
        """Path relative to docs/snaps/<theme>/index.html (so the per-theme
        page can use a viewport-prefixed path without escaping the theme
        directory)."""
        return f"{self.viewport}/{self.slug}.jpg"


def _discover_themes() -> list[str]:
    """Return themes in canonical THEME_ORDER, filtered to those with at
    least a `theme.json` so we don't list a stale folder."""
    return [t for t in THEME_ORDER if (ROOT / t / "theme.json").is_file()]


def _cells_from_manifest(theme: str) -> list[Cell] | None:
    """Read `tmp/snaps/<theme>/manifest.json` and return one Cell per
    shot. Returns None if the manifest doesn't exist (caller should fall
    back to the baseline tree). Skips any shot whose PNG has gone missing
    on disk since the manifest was written -- happens after a partial
    `bin/snap.py shoot` interrupt."""
    manifest_path = TMP_SNAPS / theme / "manifest.json"
    if not manifest_path.is_file():
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    cells: list[Cell] = []
    for shot in data.get("shots", []):
        png = ROOT / shot["path"]
        if not png.is_file():
            continue
        slug = str(shot["route"])
        base_route, _, flow = slug.partition(".")

        # Pull per-finding evidence crops out of the sibling
        # findings.json so the gallery can render them inline below the
        # failing thumbnail. Best-effort -- a missing/corrupt findings
        # JSON just yields zero crops, no exception.
        crops: list[tuple[str, str, str, str]] = []
        findings_rel = shot.get("findings_path")
        if findings_rel:
            try:
                fp_data = json.loads(
                    (ROOT / findings_rel).read_text(encoding="utf-8")
                )
                for f in fp_data.get("findings", []) or []:
                    crop_path = f.get("crop_path")
                    if not crop_path:
                        continue
                    if not (ROOT / crop_path).is_file():
                        continue
                    crops.append((
                        str(f.get("severity", "info")),
                        str(f.get("kind", "")),
                        str(f.get("message", "")),
                        str(crop_path),
                    ))
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        cells.append(
            Cell(
                theme=theme,
                viewport=str(shot["viewport"]),
                slug=slug,
                base_route=base_route,
                interaction=(flow or None),
                src_png=png,
                error_count=int(shot.get("error_count", 0)) if "error_count" in shot else None,
                warn_count=int(shot.get("warn_count", 0)) if "warn_count" in shot else None,
                crops=tuple(crops),
            )
        )
    return cells


def _cells_from_baseline(theme: str) -> list[Cell]:
    """Glob `tests/visual-baseline/<theme>/<viewport>/<slug>.png`. No
    findings JSON is committed alongside baseline PNGs, so error/warn
    counts come back as None (the gallery hides the badges in that case)."""
    cells: list[Cell] = []
    theme_root = BASELINE / theme
    if not theme_root.is_dir():
        return cells
    for viewport in VIEWPORT_ORDER:
        vp_dir = theme_root / viewport
        if not vp_dir.is_dir():
            continue
        for png in sorted(vp_dir.glob("*.png")):
            slug = png.stem
            base_route, _, flow = slug.partition(".")
            cells.append(
                Cell(
                    theme=theme,
                    viewport=viewport,
                    slug=slug,
                    base_route=base_route,
                    interaction=(flow or None),
                    src_png=png,
                    error_count=None,
                    warn_count=None,
                )
            )
    return cells


def _resolve_cells(theme: str, source: str) -> tuple[list[Cell], str]:
    """Pick the cell list according to `--source`, returning the cells AND
    the source label that produced them (so the per-theme page can show
    'tmp/snaps' vs 'baseline' in its header). `source='auto'` prefers
    tmp; falls back to baseline if tmp is empty."""
    if source == "tmp":
        cells = _cells_from_manifest(theme)
        return (cells or []), "tmp/snaps"
    if source == "baseline":
        return _cells_from_baseline(theme), "tests/visual-baseline"
    cells = _cells_from_manifest(theme)
    if cells:
        return cells, "tmp/snaps"
    return _cells_from_baseline(theme), "tests/visual-baseline"


def _interaction_index(slug: str) -> int:
    """Sort key for an interaction slug like 'home.menu-open' -- pulls the
    declared `Interaction` order out of `INTERACTIONS` so the gallery
    renders flows in the same order `snap.py` shoots them."""
    base, _, flow = slug.partition(".")
    flows = INTERACTIONS.get(base, [])
    for i, interaction in enumerate(flows):
        if interaction.name == flow:
            return i
    return 999  # unknown interaction -> trailing


def _sort_cells(cells: list[Cell]) -> list[Cell]:
    """Canonical order: viewport (mobile→wide), then base route in ROUTE_ORDER,
    then static-before-interaction, then interaction order from snap_config."""
    vp_index = {v: i for i, v in enumerate(VIEWPORT_ORDER)}
    route_index = {r: i for i, r in enumerate(ROUTE_ORDER)}
    return sorted(
        cells,
        key=lambda c: (
            vp_index.get(c.viewport, 999),
            route_index.get(c.base_route, 999),
            0 if c.interaction is None else 1,
            _interaction_index(c.slug),
        ),
    )


# ---------------------------------------------------------------------------
# Thumbnail encoding
# ---------------------------------------------------------------------------


def _encode_thumb(src_png: Path, dst_jpg: Path, *, force: bool) -> bool:
    """Re-encode `src_png` to a 600px-wide JPEG at `dst_jpg`. Skips the
    work if `dst_jpg` already exists and is newer than `src_png` (and
    `--clean` wasn't passed). Returns True if the file was (re)written."""
    dst_jpg.parent.mkdir(parents=True, exist_ok=True)
    if not force and dst_jpg.is_file() and dst_jpg.stat().st_mtime >= src_png.stat().st_mtime:
        return False
    Image = _require_pillow()
    with Image.open(src_png) as im:
        im.thumbnail((THUMB_WIDTH_PX, THUMB_MAX_HEIGHT_PX), Image.LANCZOS)
        im.convert("RGB").save(
            dst_jpg, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True
        )
    return True


def _encode_hero_card(src_png: Path, dst_jpg: Path, *, force: bool) -> bool:
    """Encode the hero card image used on the top-level snap picker.

    Unlike `_encode_thumb` (which downsamples aggressively for the dense
    per-theme grid), this keeps the source PNG's native width and crops
    to a wide 16:10 frame from the top — matching the CSS
    `object-position: center top; object-fit: cover` used by the picker
    so what gets shown in the browser is exactly what we encoded, with
    no upscale and no fractional-pixel cropping at display time.
    Returns True if the file was (re)written."""
    dst_jpg.parent.mkdir(parents=True, exist_ok=True)
    if not force and dst_jpg.is_file() and dst_jpg.stat().st_mtime >= src_png.stat().st_mtime:
        return False
    Image = _require_pillow()
    with Image.open(src_png) as im:
        # Step 1: clamp width to the hero target (only ever downsamples;
        # if the source is narrower we leave it alone rather than upscale).
        if im.width > HERO_WIDTH_PX:
            new_h = round(im.height * (HERO_WIDTH_PX / im.width))
            im = im.resize((HERO_WIDTH_PX, new_h), Image.LANCZOS)
        # Step 2: crop to the hero aspect from the top of the page —
        # the page header is always the most editorial part of the shot.
        target_w = im.width
        target_h = round(target_w * HERO_ASPECT[1] / HERO_ASPECT[0])
        if target_h < im.height:
            im = im.crop((0, 0, target_w, target_h))
        im.convert("RGB").save(
            dst_jpg, "JPEG", quality=HERO_QUALITY, optimize=True, progressive=True
        )
    return True


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


# Brand-asset link tags injected verbatim into every snap-gallery <head>.
# Identical to the constant of the same name in bin/build-redirects.py —
# kept duplicated rather than imported because both build scripts run
# standalone (no package import path) and the duplication is small enough
# that drift is caught by `bin/build-brand-assets.py --check` flagging
# any binary file mismatch + a `git grep BRAND_HEAD_TAGS` review.
BRAND_HEAD_TAGS = """\
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="alternate icon" href="/favicon.ico" sizes="16x16 32x32" type="image/x-icon">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">
<meta property="og:image" content="https://demo.regionallyfamous.com/assets/og-default.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="fifty. \u2014 AI-built WooCommerce themes on strict rails, set in DM Serif Display with a cobalt accent.">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://demo.regionallyfamous.com/assets/og-default.png">"""


SHARED_CSS = """\
/* ========================================================================
   Snap gallery — magazine-cover system
   ------------------------------------------------------------------------
   Layered on top of the site-wide /assets/style.css (loaded first), this
   stylesheet adds the gallery-specific rules: the theme picker hero
   layout, the per-theme viewport sections, and the cell grid + badges.
   Same monochrome palette + cobalt accent + hairline rules + DM Serif /
   IBM Plex Mono typography as the rest of demo.regionallyfamous.com.
   ======================================================================== */

/* Theme picker (top-level docs/snaps/index.html) — full-width "magazine
   spreads", one per theme: large hero shot on the left, italic blurb +
   stats on the right, hairline rule between rows. Replaces the old
   rounded-card grid. */
.snap-picker {
  border-top: var(--hairline) solid var(--rule);
  margin-top: 1.5rem;
}
.snap-picker .theme {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: clamp(1.5rem, 4vw, 3rem);
  padding: clamp(1.5rem, 3vw, 2.25rem) 0;
  border-bottom: var(--hairline) solid var(--rule);
  text-decoration: none;
  color: inherit;
  align-items: center;
}
.snap-picker .theme .hero {
  aspect-ratio: 16 / 10;
  border: var(--hairline) solid var(--rule);
  background: var(--paper) center / cover no-repeat;
  overflow: hidden;
}
.snap-picker .theme .hero img { width: 100%; height: 100%; object-fit: cover; object-position: center top; display: block; }
.snap-picker .theme .meta { display: flex; flex-direction: column; gap: .75rem; }
.snap-picker .theme .index {
  font-family: var(--mono);
  font-size: .7rem;
  text-transform: uppercase;
  letter-spacing: .1em;
}
.snap-picker .theme h2 {
  font-family: var(--serif-display);
  font-weight: 400;
  font-size: clamp(2.5rem, 7vw, 5.5rem);
  line-height: .9;
  letter-spacing: -.03em;
  margin: 0;
}
.snap-picker .theme .blurb {
  font-family: var(--serif-text);
  font-style: italic;
  font-size: 1.05rem;
  line-height: 1.4;
  margin: 0;
}
.snap-picker .theme .stats {
  display: flex;
  flex-wrap: wrap;
  gap: .65rem 1.5rem;
  font-family: var(--mono);
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .1em;
}
.snap-picker .theme .stats .bad { color: var(--accent); }
.snap-picker .theme .stats .warn { color: var(--ink); border-bottom: 1px dotted var(--ink); padding-bottom: 1px; }
.snap-picker .theme .open {
  font-family: var(--mono);
  font-size: .7rem;
  text-transform: uppercase;
  letter-spacing: .1em;
  margin-top: .25rem;
}
.snap-picker .theme .open .arrow { color: var(--accent); }
.snap-picker .theme:hover .hero { outline: 2px solid var(--accent); outline-offset: -1px; }
@media (max-width: 720px) {
  .snap-picker .theme { grid-template-columns: 1fr; }
}

/* Per-theme page (docs/snaps/<theme>/index.html) — one section per
   viewport (mobile / tablet / desktop / wide), each section sized to
   reflect what that viewport actually shoots:

     - mobile + tablet: tall portrait cells in a denser grid
     - desktop + wide: short landscape cells in a sparser grid

   Without per-viewport tuning, every cell shared a single 4/5 portrait
   frame — desktop and wide screenshots (which are landscape full-page
   PNGs averaging ~600x1100) ended up slivered into a tiny strip across
   the top of an oversized portrait box, leaving the rest of the cell
   blank and the whole grid reading as broken. The classes below are
   stamped onto each `<section class="viewport-section viewport-{vp}">`
   wrapper by `_render_theme_page` so the grid + frame ratio always
   tracks the source aspect. */
.viewport-section { margin-top: clamp(2rem, 4vw, 3rem); }
.viewport-section h2 {
  margin: 0 0 1rem;
  font-family: var(--mono);
  font-size: .72rem;
  font-weight: 500;
  letter-spacing: .12em;
  text-transform: uppercase;
  padding-bottom: .65rem;
  border-bottom: var(--hairline) solid var(--rule);
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.viewport-section h2 .count { opacity: .55; font-weight: 400; }

.cells {
  display: grid;
  gap: 1.5rem 1.25rem;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
}
.viewport-mobile .cells   { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
.viewport-tablet .cells   { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.viewport-desktop .cells  { grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.viewport-wide .cells     { grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }

.cell { display: flex; flex-direction: column; gap: .5rem; }
.cell .frame {
  border: var(--hairline) solid var(--rule);
  background: var(--paper);
  overflow: hidden;
  aspect-ratio: 4/5;
  display: block;
  transition: outline .12s ease;
}
/* Per-viewport frame ratios: roughly mirror each viewport's actual
   aspect so the cropped top-of-page preview reads as "a phone" or
   "a desktop" at a glance, not as a uniformly portrait postage stamp. */
.viewport-mobile  .cell .frame { aspect-ratio: 9 / 16; }
.viewport-tablet  .cell .frame { aspect-ratio: 3 / 4; }
.viewport-desktop .cell .frame { aspect-ratio: 16 / 11; }
.viewport-wide    .cell .frame { aspect-ratio: 16 / 9; }
.cell .frame:hover, .cell .frame:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -1px;
  border-color: var(--accent);
}
.cell .frame img { width: 100%; height: 100%; object-fit: cover; object-position: center top; display: block; }
.cell .meta { display: flex; flex-wrap: wrap; gap: .35rem .65rem; align-items: baseline; }
.cell .meta .slug {
  font-family: var(--mono);
  font-size: .72rem;
  font-weight: 500;
  letter-spacing: .03em;
}
.cell .meta .desc {
  font-family: var(--serif-text);
  font-style: italic;
  color: var(--muted);
  font-size: .82rem;
  flex-basis: 100%;
  line-height: 1.35;
}
.cell .badges { display: inline-flex; gap: .3rem; }
.cell .badge {
  display: inline-block;
  padding: 0 .35rem;
  border: 1px solid var(--ink);
  font-family: var(--mono);
  font-size: .58rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: .1em;
  line-height: 1.55;
}
.cell .badge.err { color: var(--accent); border-color: var(--accent); }
.cell .badge.warn { color: var(--ink); }
.cell .badge.flow { color: var(--ink); border-style: dashed; }

/* Per-finding evidence crops -- a horizontal strip of small JPGs of
   the offending elements, captured by bin/snap.py alongside the full
   page screenshot. Reviewers see the full-page thumbnail to set
   context, then the crops to identify exactly which element fired
   which check, without scrubbing through a 3000px tall PNG. */
.cell .crops {
  display: flex;
  flex-wrap: wrap;
  gap: .35rem;
  padding: .25rem 0 0;
}
.cell .crop {
  display: flex;
  flex-direction: column;
  gap: .15rem;
  text-decoration: none;
  color: inherit;
  border: var(--hairline) solid var(--rule);
  background: var(--paper);
  padding: 2px;
  max-width: 110px;
  font-family: var(--mono);
  font-size: .54rem;
  line-height: 1.35;
  text-transform: uppercase;
  letter-spacing: .06em;
  transition: border-color .12s ease;
}
.cell .crop:hover, .cell .crop:focus-visible {
  border-color: var(--accent);
  outline: none;
}
.cell .crop img {
  display: block;
  width: 100%;
  height: 60px;
  object-fit: cover;
  object-position: center top;
}
.cell .crop-kind {
  display: block;
  padding: 1px 3px 0;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cell .crop-error { border-color: var(--accent); }
.cell .crop-error .crop-kind { color: var(--accent); }
.cell .crop-warn  { border-color: var(--ink); }
.cell .crop-info  { opacity: .8; }

/* Snap-page header (re-uses .subhero from /assets/style.css) */
.snap-header {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: baseline;
  justify-content: space-between;
  font-family: var(--mono);
  font-size: .72rem;
  text-transform: uppercase;
  letter-spacing: .1em;
  padding: .5rem 0 .25rem;
}
.snap-header a { text-decoration: none; }
.snap-header a:hover { color: var(--accent); }
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _render_badges(cell: Cell) -> str:
    parts: list[str] = []
    if cell.interaction:
        parts.append(f'<span class="badge flow">{_esc(cell.interaction)}</span>')
    if cell.error_count:
        parts.append(f'<span class="badge err">{cell.error_count} err</span>')
    if cell.warn_count:
        parts.append(f'<span class="badge warn">{cell.warn_count} warn</span>')
    if not parts:
        return ""
    return f'<span class="badges">{"".join(parts)}</span>'


def _render_crops(cell: Cell) -> str:
    """Render per-finding evidence crops below the failing thumbnail.

    Each crop is a small JPG of the offending element captured by
    `bin/snap.py`'s `_capture_finding_crops`. The reviewer sees the
    full-page thumbnail to set context, then a row of cropped offenders
    to identify exactly which element fired which check, without having
    to scrub through a 3000px tall full-page screenshot.
    """
    if not cell.crops:
        return ""
    items: list[str] = []
    for sev, kind, msg, src_rel in cell.crops:
        src = ROOT / src_rel
        href = f"{cell.viewport}/{src.name}"
        # Truncate the message a bit so the caption stays a one-liner;
        # the full message is in review.md / findings.json.
        short = (msg[:140] + "…") if len(msg) > 140 else msg
        sev_class = sev if sev in ("error", "warn", "info") else "info"
        items.append(
            f'<a class="crop crop-{sev_class}" href="{_esc(href)}" '
            f'target="_blank" rel="noopener" '
            f'title="{_esc(sev.upper())} · {_esc(kind)} · {_esc(short)}">'
            f'<img loading="lazy" decoding="async" src="{_esc(href)}" '
            f'alt="{_esc(kind)}: {_esc(short)}">'
            f'<span class="crop-kind">{_esc(kind)}</span>'
            f'</a>'
        )
    return f'<div class="crops">{"".join(items)}</div>'


def _render_theme_page(theme: str, cells: list[Cell], source_label: str) -> str:
    """Build the per-theme HTML grid, grouped by viewport. Layered on top
    of the site-wide /assets/style.css so the gallery shares the magazine-
    cover system (mono labels, hairline rules, cobalt accent on hover)
    with the landing page and the concept queue."""
    by_viewport: dict[str, list[Cell]] = {v: [] for v in VIEWPORT_ORDER}
    for c in cells:
        by_viewport.setdefault(c.viewport, []).append(c)

    blurb = THEME_BLURBS.get(theme, "")
    sections: list[str] = []
    for vp in VIEWPORT_ORDER:
        vp_cells = by_viewport.get(vp, [])
        if not vp_cells:
            continue
        cell_html: list[str] = []
        for c in vp_cells:
            route = ROUTE_BY_SLUG.get(c.base_route)
            desc = route.description if route else ""
            cell_html.append(
                f'''<div class="cell">
  <a class="frame" href="{_esc(c.thumb_rel)}" target="_blank" rel="noopener">
    <img loading="lazy" decoding="async" src="{_esc(c.thumb_rel)}" alt="{_esc(theme)} {_esc(vp)} {_esc(c.slug)}">
  </a>
  {_render_crops(c)}
  <div class="meta">
    <span class="slug">{_esc(c.slug)}</span>
    {_render_badges(c)}
    <span class="desc">{_esc(desc)}</span>
  </div>
</div>'''
            )
        sections.append(
            f'''<section class="viewport-section viewport-{_esc(vp)}">
  <h2><span>{_esc(vp)}</span><span class="count">{len(vp_cells)} shot{"s" if len(vp_cells) != 1 else ""}</span></h2>
  <div class="cells">
    {"".join(cell_html)}
  </div>
</section>'''
        )

    body = (
        "".join(sections)
        if sections
        else f'<p class="empty-note">No snaps on disk for this theme. Run <code>python3 bin/snap.py shoot {_esc(theme)}</code> first.</p>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(theme)} — Snap gallery — Fifty</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Every snap PNG for the {_esc(theme)} block theme, grouped by viewport. Source: {_esc(source_label)}.">
<meta name="robots" content="noindex">
{BRAND_HEAD_TAGS}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Serif+Text:ital@0;1&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/assets/style.css">
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<header class="masthead">
  <span class="left"><a href="/">← Fifty</a></span>
  <span class="center">AI agents, on strict rails</span>
  <span class="right">Snaps · {_esc(theme)}</span>
</header>
<main>
  <section class="subhero">
    <p class="eyebrow">Pixel contract · {_esc(theme)}</p>
    <h1>{_esc(theme)}<span style="color:var(--accent)">.</span></h1>
    <p class="deck">{_esc(blurb)}</p>
  </section>
  <div class="snap-header">
    <span><a href="../">← all themes</a> · source <code>{_esc(source_label)}</code></span>
    <span><a href="../../{_esc(theme)}/">Open {_esc(theme)} in Playground →</a></span>
  </div>
  {body}
</main>
<footer class="colophon">
  <span class="left"><a href="https://github.com/RegionallyFamous/fifty">github.com/RegionallyFamous/fifty</a></span>
  <span class="center">Generated by <code>bin/build-snap-gallery.py</code></span>
  <span class="right"><a href="../">← All themes</a></span>
</footer>
</body>
</html>
"""


def _render_index_page(theme_summaries: list[dict]) -> str:
    """Top-level docs/snaps/index.html — magazine-cover spread per theme.
    Each row pairs the desktop/home shot (or first available cell) with a
    serif-display name, italic blurb, and mono-stat strip. Replaces the
    rounded-card grid."""
    total = len(theme_summaries)
    rows: list[str] = []
    for i, s in enumerate(theme_summaries, start=1):
        theme = s["theme"]
        blurb = THEME_BLURBS.get(theme, "")
        hero_rel = s["hero_rel"]
        stats = s["stats"]
        stat_bits: list[str] = [f'<span>{stats["cells"]} shots</span>']
        if stats.get("err"):
            stat_bits.append(f'<span class="bad">{stats["err"]} err</span>')
        if stats.get("warn"):
            stat_bits.append(f'<span class="warn">{stats["warn"]} warn</span>')
        stat_bits.append(f'<span>source {_esc(s["source"])}</span>')
        hero_html = (
            f'<img loading="lazy" decoding="async" src="{_esc(hero_rel)}" alt="{_esc(theme)} desktop home">'
            if hero_rel
            else ""
        )
        rows.append(
            f'''<a class="theme" href="{_esc(theme)}/">
  <div class="hero">{hero_html}</div>
  <div class="meta">
    <span class="index">Theme {i:02d} / {total:02d}</span>
    <h2>{_esc(theme)}</h2>
    <p class="blurb">{_esc(blurb)}</p>
    <div class="stats">{"".join(stat_bits)}</div>
    <span class="open">View grid <span class="arrow">→</span></span>
  </div>
</a>'''
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Snap gallery — Fifty</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Every theme's snap PNGs at a glance — no Playground boot required.">
<meta name="robots" content="noindex">
{BRAND_HEAD_TAGS}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Serif+Text:ital@0;1&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/assets/style.css">
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="masthead">
  <span class="left"><a href="/">← Fifty</a></span>
  <span class="center">AI agents, on strict rails</span>
  <span class="right">The visual contract</span>
</header>
<main>
  <section class="subhero">
    <p class="eyebrow">The visual contract</p>
    <h1>snap gallery<span style="color:var(--accent)">.</span></h1>
    <p class="deck">The visual contract for every theme, at every viewport. Screenshots are baselined; any pixel diff turns CI red. This is how the agent ships designs that don&rsquo;t quietly regress between sessions.</p>
  </section>
  <section class="snap-picker" aria-label="Themes">
    {"".join(rows)}
  </section>
</main>
<footer class="colophon">
  <span class="left"><a href="https://github.com/RegionallyFamous/fifty">github.com/RegionallyFamous/fifty</a></span>
  <span class="center">Generated from on-disk PNGs · no live Playground required</span>
  <span class="right"><a href="/">← All themes</a></span>
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def build(themes: list[str], source: str, *, clean: bool) -> int:
    """Encode every cell's thumbnail and emit per-theme + top-level HTML.
    Returns the number of themes that produced at least one cell (0 means
    every theme came back empty -- typically because the user passed
    `--source tmp` without first running `bin/snap.py shoot`)."""
    DOCS_SNAPS.mkdir(parents=True, exist_ok=True)
    (DOCS_SNAPS / "assets").mkdir(parents=True, exist_ok=True)
    (DOCS_SNAPS / "assets" / "style.css").write_text(SHARED_CSS, encoding="utf-8")

    summaries: list[dict] = []
    for theme in themes:
        cells, source_label = _resolve_cells(theme, source)
        cells = _sort_cells(cells)
        if not cells:
            print(f"[{theme}] no PNGs found (source={source}); skipping")
            continue

        theme_dir = DOCS_SNAPS / theme
        if clean and theme_dir.is_dir():
            shutil.rmtree(theme_dir)
        theme_dir.mkdir(parents=True, exist_ok=True)

        encoded = 0
        for c in cells:
            dst = theme_dir / c.viewport / f"{c.slug}.jpg"
            if _encode_thumb(c.src_png, dst, force=clean):
                encoded += 1
            # Mirror the per-finding evidence crops into the gallery dir
            # so the per-theme page can link to them with a viewport-
            # relative href. Same filename as the source so the cell
            # renderer doesn't need to track a separate name.
            for _sev, _kind, _msg, src_rel in c.crops:
                src = ROOT / src_rel
                if not src.is_file():
                    continue
                crop_dst = theme_dir / c.viewport / src.name
                crop_dst.parent.mkdir(parents=True, exist_ok=True)
                if (
                    clean
                    or not crop_dst.is_file()
                    or crop_dst.stat().st_mtime < src.stat().st_mtime
                ):
                    shutil.copy2(src, crop_dst)

        index_html = _render_theme_page(theme, cells, source_label)
        (theme_dir / "index.html").write_text(index_html, encoding="utf-8")

        # Hero for the top-level card. Prefer desktop/home and re-encode
        # it as a sharp 1280-wide 16:10 crop (`<theme>/hero.jpg`) so the
        # large picker card doesn't 2x-upscale the dense gallery thumb.
        # Falls back to the first available thumbnail if desktop/home
        # isn't present (e.g. a theme that only shipped mobile cells).
        # Path is relative to docs/snaps/index.html.
        hero_rel = ""
        hero_src: Path | None = None
        for c in cells:
            if c.viewport == "desktop" and c.slug == "home":
                hero_src = c.src_png
                break
        if hero_src is not None:
            hero_dst = theme_dir / "hero.jpg"
            _encode_hero_card(hero_src, hero_dst, force=clean)
            hero_rel = f"{theme}/hero.jpg"
        elif cells:
            hero_rel = f"{theme}/{cells[0].thumb_rel}"

        err_total = sum(c.error_count or 0 for c in cells)
        warn_total = sum(c.warn_count or 0 for c in cells)
        summaries.append(
            {
                "theme": theme,
                "hero_rel": hero_rel,
                "source": source_label,
                "stats": {"cells": len(cells), "err": err_total, "warn": warn_total},
            }
        )
        print(f"[{theme}] {len(cells)} cells; encoded {encoded}; source={source_label}")

    if summaries:
        (DOCS_SNAPS / "index.html").write_text(_render_index_page(summaries), encoding="utf-8")

    return len(summaries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate docs/snaps/ from tmp/snaps/ (or tests/visual-baseline/).",
    )
    parser.add_argument(
        "--theme",
        action="append",
        default=None,
        help="Limit to one or more themes (repeatable). Defaults to every theme with a theme.json.",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "tmp", "baseline"),
        default="auto",
        help=(
            "Where to read PNGs from. 'auto' (default) prefers tmp/snaps then "
            "falls back to tests/visual-baseline per theme. 'tmp' requires a "
            "manifest.json. 'baseline' uses only committed PNGs."
        ),
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe each theme's docs/snaps/<theme>/ folder before rebuilding (forces full re-encode).",
    )
    args = parser.parse_args(argv)

    themes = args.theme or _discover_themes()
    if not themes:
        print("No themes found.", file=sys.stderr)
        return 2
    n = build(themes, args.source, clean=args.clean)
    if n == 0:
        print(
            "No themes produced any cells. Run `python3 bin/snap.py shoot --all` "
            "first if you want fresh imagery, or pass `--source baseline` to use "
            "the committed reference PNGs.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
