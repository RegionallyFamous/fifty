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
    "chonk": "Neo-brutalist: cream + 4px black borders, hard offset shadows, no rounded corners.",
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


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


SHARED_CSS = """\
:root { color-scheme: dark light; }
*, *::before, *::after { box-sizing: border-box; }
html, body {
  margin: 0;
  background: #0f0f10;
  color: #f5f5f4;
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
}
a { color: inherit; }
main { max-width: 90rem; margin: 0 auto; padding: clamp(1.5rem, 3vw, 2.5rem) clamp(1rem, 3vw, 2rem); }
header.page { margin-bottom: 2.5rem; display: flex; flex-wrap: wrap; gap: 1rem; align-items: baseline; justify-content: space-between; }
header.page h1 { font-size: clamp(1.5rem, 3vw, 2.25rem); margin: 0; font-weight: 700; letter-spacing: -.01em; }
header.page p { margin: .25rem 0 0; color: #a8a29e; font-size: .9rem; max-width: 38rem; }
header.page .crumbs { font-size: .85rem; color: #a8a29e; }
header.page .crumbs a { color: #d6d3d1; text-decoration: none; }
header.page .crumbs a:hover { text-decoration: underline; }

/* Theme picker (top-level) */
.themes { display: grid; gap: 1.25rem; grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr)); }
.theme-card {
  display: flex; flex-direction: column; gap: .75rem;
  border: 1px solid #2c2a27; border-radius: 14px; padding: 1.25rem;
  background: #1a1917; text-decoration: none; color: inherit;
  transition: border-color 160ms ease, transform 160ms ease;
}
.theme-card:hover { border-color: #57534e; transform: translateY(-1px); }
.theme-card h2 { margin: 0; font-size: 1.25rem; font-weight: 600; }
.theme-card p { margin: 0; color: #a8a29e; font-size: .9rem; }
.theme-card .hero {
  width: 100%; aspect-ratio: 16/10;
  background: #0a0a0b center/cover no-repeat;
  border-radius: 8px; border: 1px solid #2c2a27;
  overflow: hidden;
}
.theme-card .hero img { width: 100%; height: 100%; object-fit: cover; object-position: center top; display: block; }
.theme-card .stats { display: flex; gap: .75rem; font-size: .8rem; color: #a8a29e; }
.theme-card .stats span.bad { color: #fda4af; }
.theme-card .stats span.warn { color: #fcd34d; }

/* Per-theme page */
.viewport-section { margin-top: 2.5rem; }
.viewport-section h2 {
  margin: 0 0 1rem; font-size: 1rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: #a8a29e; padding-bottom: .5rem; border-bottom: 1px solid #2c2a27;
}
.cells {
  display: grid; gap: 1.25rem;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}
.cell { display: flex; flex-direction: column; gap: .4rem; }
.cell .frame {
  background: #0a0a0b; border: 1px solid #2c2a27; border-radius: 8px;
  overflow: hidden; aspect-ratio: 4/5; display: block;
  transition: border-color 160ms ease, transform 160ms ease;
}
.cell .frame:hover { border-color: #78716c; transform: translateY(-1px); }
.cell .frame img { width: 100%; height: 100%; object-fit: cover; object-position: center top; display: block; }
.cell .meta { display: flex; flex-wrap: wrap; gap: .35rem; align-items: baseline; }
.cell .meta .slug { font-size: .85rem; font-weight: 500; }
.cell .meta .desc { color: #78716c; font-size: .75rem; flex-basis: 100%; line-height: 1.35; }
.cell .badges { display: inline-flex; gap: .35rem; }
.badge {
  display: inline-block; padding: .1rem .45rem; border-radius: 9999px;
  font-size: .7rem; font-weight: 600; line-height: 1.4;
}
.badge.err { background: #7f1d1d; color: #fecaca; }
.badge.warn { background: #78350f; color: #fde68a; }
.badge.flow { background: #1e3a8a; color: #c7d2fe; }

footer.page {
  margin-top: 4rem; padding-top: 1.5rem;
  border-top: 1px solid #2c2a27;
  font-size: .8rem; color: #78716c;
  display: flex; flex-wrap: wrap; gap: 1rem; justify-content: space-between;
}
footer.page a { color: #d6d3d1; }

@media (prefers-color-scheme: light) {
  html, body { background: #fafaf9; color: #1c1917; }
  header.page p, header.page .crumbs, .theme-card p, .cell .meta .desc, footer.page { color: #57534e; }
  header.page .crumbs a, footer.page a { color: #1c1917; }
  .theme-card { background: #fff; border-color: #e7e5e4; }
  .theme-card:hover { border-color: #a8a29e; }
  .theme-card .hero { background-color: #f5f5f4; border-color: #e7e5e4; }
  .viewport-section h2 { color: #57534e; border-bottom-color: #e7e5e4; }
  .cell .frame { background: #f5f5f4; border-color: #e7e5e4; }
  .cell .frame:hover { border-color: #78716c; }
  .badge.err { background: #fee2e2; color: #991b1b; }
  .badge.warn { background: #fef3c7; color: #92400e; }
  .badge.flow { background: #e0e7ff; color: #3730a3; }
  footer.page { border-top-color: #e7e5e4; }
}
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


def _render_theme_page(theme: str, cells: list[Cell], source_label: str) -> str:
    """Build the per-theme HTML grid, grouped by viewport."""
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
  <div class="meta">
    <span class="slug">{_esc(c.slug)}</span>
    {_render_badges(c)}
    <span class="desc">{_esc(desc)}</span>
  </div>
</div>'''
            )
        sections.append(
            f'''<section class="viewport-section">
  <h2>{_esc(vp)} <span style="opacity:.6;font-weight:400">· {len(vp_cells)} shot{"s" if len(vp_cells) != 1 else ""}</span></h2>
  <div class="cells">
    {"".join(cell_html)}
  </div>
</section>'''
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(theme)} — Snap gallery — Fifty</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Every snap PNG for the {_esc(theme)} block theme, grouped by viewport. Source: {_esc(source_label)}.">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<main>
  <header class="page">
    <div>
      <div class="crumbs"><a href="../">snaps</a> / <strong>{_esc(theme)}</strong></div>
      <h1>{_esc(theme)}</h1>
      <p>{_esc(blurb)}</p>
    </div>
    <div class="crumbs">
      Source: <code>{_esc(source_label)}</code>
      · <a href="../../{_esc(theme)}/">Open in Playground →</a>
    </div>
  </header>
  {"".join(sections) if sections else "<p>No snaps on disk for this theme. Run <code>python3 bin/snap.py shoot " + _esc(theme) + "</code> first.</p>"}
  <footer class="page">
    <span><a href="../">All themes</a> · <a href="../../">Fifty home</a></span>
    <span><a href="https://github.com/RegionallyFamous/fifty">github.com/RegionallyFamous/fifty</a></span>
  </footer>
</main>
</body>
</html>
"""


def _render_index_page(theme_summaries: list[dict]) -> str:
    """Top-level docs/snaps/index.html. Each theme card carries the
    desktop/home shot as its hero image (or whatever it falls back to if
    desktop/home isn't available)."""
    cards: list[str] = []
    for s in theme_summaries:
        theme = s["theme"]
        blurb = THEME_BLURBS.get(theme, "")
        hero_rel = s["hero_rel"]
        stats = s["stats"]
        stat_bits: list[str] = []
        stat_bits.append(f'<span>{stats["cells"]} shots</span>')
        if stats.get("err"):
            stat_bits.append(f'<span class="bad">{stats["err"]} err</span>')
        if stats.get("warn"):
            stat_bits.append(f'<span class="warn">{stats["warn"]} warn</span>')
        stat_bits.append(f'<span>· {s["source"]}</span>')
        hero_html = (
            f'<img loading="lazy" decoding="async" src="{_esc(hero_rel)}" alt="{_esc(theme)} desktop home">'
            if hero_rel
            else ""
        )
        cards.append(
            f'''<a class="theme-card" href="{_esc(theme)}/">
  <div class="hero">{hero_html}</div>
  <h2>{_esc(theme)}</h2>
  <p>{_esc(blurb)}</p>
  <div class="stats">{"".join(stat_bits)}</div>
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
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<main>
  <header class="page">
    <div>
      <div class="crumbs"><a href="../">fifty</a> / <strong>snaps</strong></div>
      <h1>Snap gallery</h1>
      <p>Every snap PNG for every theme, grouped by viewport. Generated from on-disk PNGs by <code>bin/build-snap-gallery.py</code>; rebuild after <code>bin/snap.py shoot</code>.</p>
    </div>
    <div class="crumbs"><a href="../">← Open a Playground</a></div>
  </header>
  <section class="themes">
    {"".join(cards)}
  </section>
  <footer class="page">
    <span>Generated by <code>bin/build-snap-gallery.py</code> from on-disk PNGs (no live Playground required).</span>
    <span><a href="https://github.com/RegionallyFamous/fifty">github.com/RegionallyFamous/fifty</a></span>
  </footer>
</main>
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

        index_html = _render_theme_page(theme, cells, source_label)
        (theme_dir / "index.html").write_text(index_html, encoding="utf-8")

        # Hero for the top-level card: prefer desktop/home; fall back to
        # the first available cell. Path is relative to docs/snaps/index.html.
        hero_rel = ""
        for c in cells:
            if c.viewport == "desktop" and c.slug == "home":
                hero_rel = f"{theme}/{c.thumb_rel}"
                break
        if not hero_rel and cells:
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
