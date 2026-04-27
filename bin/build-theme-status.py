#!/usr/bin/env python3
"""Generate docs/themes/index.html -- the theme-status dashboard.

Tier 2.2 of the pre-100-themes hardening plan. One row per theme, one
column per gate. At six themes this is a curiosity; at 100 themes it's
the only view that answers "which themes are shippable right now?" in
one glance.

Columns (in left-to-right order)
--------------------------------
  theme          slug (link to docs/<slug>/ if it exists).
  stage          readiness.json stage (shipping | incubating | retired
                 | <missing>). Incubating is orange; retired is grey.
  boot           boots headless: green when `tmp/<slug>-boot.json` ok,
                 red when not, grey when never run.
  baseline age   mtime of tests/visual-baseline/<slug>/desktop/home.png.
                 Green <=7d, yellow <=30d, red >30d, grey when missing.
  microcopy      pass/fail of `check.py::check_pattern_microcopy_distinct`
                 + `check_all_rendered_text_distinct_across_themes`. Uses
                 the uniqueness cache so this is fast.
  images         pass/fail of `check_product_images_unique_across_themes`
                 + `check_hero_images_unique_across_themes` + theme-
                 screenshot distinctness.
  vision         vision-review status: "reviewed" if
                 `<theme>/.vision-reviewed` marker exists (Tier 2.3 will
                 wire this to the PR label); otherwise "needed" for
                 shipping themes, "n/a" for incubating/retired. Grey
                 placeholder today.

Output
------
Writes `docs/themes/index.html` (self-contained HTML, pulls in the
site-wide `docs/assets/style.css` for consistency). Safe to run
offline; uses only file-system evidence already present after the
static gate + snap report.

Usage
-----
    python3 bin/build-theme-status.py           # write docs/themes/index.html
    python3 bin/build-theme-status.py --check   # exit 1 if dashboard is stale

The `--check` mode is intended for CI: it regenerates the HTML in
memory and fails when the committed file differs, mirroring the
`build-index.py --check` pattern.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, docs_assets_cache_stamp, iter_themes
from _readiness import load_readiness

OUT_PATH = MONOREPO_ROOT / "docs" / "themes" / "index.html"
BASELINE_ROOT = MONOREPO_ROOT / "tests" / "visual-baseline"
TMP_DIR = MONOREPO_ROOT / "tmp"


# ---------------------------------------------------------------------------
# Per-theme status collection
# ---------------------------------------------------------------------------

@dataclass
class CellStatus:
    """One cell in the status table."""
    tone: str  # "green" | "yellow" | "red" | "grey"
    label: str
    detail: str = ""


@dataclass
class ThemeRow:
    slug: str
    stage: str
    stage_source_exists: bool
    cells: dict[str, CellStatus] = field(default_factory=dict)
    summary: str = ""
    owner: str = ""
    last_checked: str = ""


def _baseline_age_cell(slug: str) -> CellStatus:
    home = BASELINE_ROOT / slug / "desktop" / "home.png"
    if not home.is_file():
        return CellStatus(tone="grey", label="none", detail="no baseline/desktop/home.png")
    age_s = time.time() - home.stat().st_mtime
    age_days = age_s / 86400.0
    if age_days <= 7:
        tone = "green"
    elif age_days <= 30:
        tone = "yellow"
    else:
        tone = "red"
    label = f"{age_days:.1f}d"
    mtime = _dt.datetime.fromtimestamp(home.stat().st_mtime).strftime("%Y-%m-%d")
    return CellStatus(tone=tone, label=label, detail=f"mtime {mtime}")


def _boot_cell(slug: str) -> CellStatus:
    path = TMP_DIR / f"{slug}-boot.json"
    if not path.is_file():
        return CellStatus(tone="grey", label="unknown", detail=f"no tmp/{slug}-boot.json run yet")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CellStatus(tone="red", label="unreadable", detail=f"{exc}")
    ok = bool(data.get("ok"))
    elapsed = data.get("elapsed_s")
    detail_parts: list[str] = []
    if isinstance(elapsed, (int, float)):
        detail_parts.append(f"{elapsed:.1f}s")
    reasons = data.get("reasons") or []
    if reasons:
        detail_parts.append(reasons[0] if isinstance(reasons[0], str) else str(reasons[0]))
    return CellStatus(
        tone="green" if ok else "red",
        label="boots" if ok else "fails",
        detail=" -- ".join(detail_parts),
    )


def _run_named_check(check_name: str, theme_dir: Path) -> CellStatus:
    """Invoke a check.py check function with ROOT pinned to `theme_dir`.

    We import check.py lazily (it's an 8k-line module) and re-use the
    uniqueness cache so the dashboard walk is cheap at 100 themes.
    On any exception -- the check crashed, not failed -- we emit grey
    with the exception text in the detail. That never makes the
    dashboard crash mid-run when a single theme is malformed.
    """
    try:
        import check as _check
    except Exception as exc:  # pragma: no cover - only in broken envs
        return CellStatus(tone="grey", label="unknown", detail=f"import check.py failed: {exc}")
    fn = getattr(_check, check_name, None)
    if fn is None:
        return CellStatus(tone="grey", label="unknown", detail=f"check.py has no {check_name}")
    prev_root = _check.ROOT
    _check.ROOT = theme_dir
    try:
        result = fn()
    except Exception as exc:
        _check.ROOT = prev_root
        return CellStatus(tone="grey", label="error", detail=str(exc)[:160])
    _check.ROOT = prev_root
    if result.skipped:
        return CellStatus(tone="grey", label="skip", detail=(result.details[0] if result.details else ""))
    if result.passed:
        return CellStatus(tone="green", label="pass", detail=(result.details[0] if result.details else ""))
    # Fail -- first detail line is the most informative.
    return CellStatus(tone="red", label="fail", detail=(result.details[0] if result.details else ""))


def _combine_cells(cells: list[CellStatus]) -> CellStatus:
    """Fold 2+ check-backed cells into one. red>yellow>grey>green."""
    tones = {c.tone for c in cells}
    if "red" in tones:
        tone = "red"
    elif "yellow" in tones:
        tone = "yellow"
    elif "grey" in tones and "green" not in tones:
        tone = "grey"
    else:
        tone = "green"
    label_of = {
        "red": "fail",
        "yellow": "warn",
        "grey": "skip",
        "green": "pass",
    }
    # Surface whichever component was worst.
    worst = next((c for c in cells if c.tone == tone), cells[0])
    return CellStatus(tone=tone, label=label_of[tone], detail=worst.detail)


def _vision_cell(slug: str, stage: str) -> CellStatus:
    """Placeholder vision-review gate. Tier 2.3 replaces this with the
    label-from-PR signal; until then we look for a sibling marker
    file, which a human can drop in to acknowledge a review pass.
    """
    marker = MONOREPO_ROOT / slug / ".vision-reviewed"
    if marker.is_file():
        return CellStatus(tone="green", label="reviewed", detail=marker.name)
    if stage in ("incubating", "retired"):
        return CellStatus(tone="grey", label="n/a", detail=f"stage={stage}")
    return CellStatus(tone="yellow", label="needed", detail="no .vision-reviewed marker")


def _stage_cell(stage: str, source_exists: bool) -> CellStatus:
    tone_of = {
        "shipping": "green",
        "incubating": "yellow",
        "retired": "grey",
    }
    tone = tone_of.get(stage, "red")
    detail = stage if source_exists else f"{stage} (default, no readiness.json)"
    return CellStatus(tone=tone, label=stage, detail=detail)


def collect_rows() -> list[ThemeRow]:
    """Walk every theme (regardless of stage) and build its status row."""
    rows: list[ThemeRow] = []
    # stages=() opts into EVERY theme including incubating/retired --
    # the dashboard is the one place we want to see retirees so
    # operators remember they still exist.
    for theme_dir in iter_themes(stages=()):
        slug = theme_dir.name
        readiness = load_readiness(theme_dir)
        row = ThemeRow(
            slug=slug,
            stage=readiness.stage,
            stage_source_exists=readiness.exists,
            summary=readiness.summary,
            owner=readiness.owner,
            last_checked=readiness.last_checked,
        )
        row.cells["stage"] = _stage_cell(readiness.stage, readiness.exists)
        row.cells["boot"] = _boot_cell(slug)
        row.cells["baseline"] = _baseline_age_cell(slug)
        row.cells["microcopy"] = _combine_cells([
            _run_named_check("check_pattern_microcopy_distinct", theme_dir),
            _run_named_check("check_all_rendered_text_distinct_across_themes", theme_dir),
            _run_named_check("check_wc_microcopy_distinct_across_themes", theme_dir),
        ])
        row.cells["images"] = _combine_cells([
            _run_named_check("check_product_images_unique_across_themes", theme_dir),
            _run_named_check("check_hero_images_unique_across_themes", theme_dir),
            _run_named_check("check_theme_screenshots_distinct", theme_dir),
        ])
        row.cells["vision"] = _vision_cell(slug, readiness.stage)
        rows.append(row)
    rows.sort(key=lambda r: (0 if r.stage == "shipping" else 1 if r.stage == "incubating" else 2, r.slug))
    return rows


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

COLUMNS: list[tuple[str, str]] = [
    ("stage", "Stage"),
    ("boot", "Boot smoke"),
    ("baseline", "Baseline age"),
    ("microcopy", "Microcopy distinct"),
    ("images", "Images unique"),
    ("vision", "Vision reviewed"),
]

TONE_COLOR = {
    "green": "#2a7a3d",
    "yellow": "#c67a00",
    "red": "#b73a3a",
    "grey": "#7a7a7a",
}


def _render_cell(cell: CellStatus) -> str:
    color = TONE_COLOR.get(cell.tone, "#7a7a7a")
    label = html.escape(cell.label)
    detail = html.escape(cell.detail)
    return (
        f'<td class="cell tone-{cell.tone}" title="{detail}">'
        f'<span class="dot" style="background:{color}"></span>'
        f'<span class="label">{label}</span>'
        f"</td>"
    )


def _render_row(row: ThemeRow) -> str:
    slug = html.escape(row.slug)
    link_target = MONOREPO_ROOT / "docs" / row.slug / "index.html"
    if link_target.is_file():
        slug_cell = f'<a href="../{slug}/">{slug}</a>'
    else:
        slug_cell = slug
    summary_cell = html.escape(row.summary or "")
    owner_cell = html.escape(row.owner or "")
    cells_html = "".join(_render_cell(row.cells[key]) for key, _ in COLUMNS)
    return (
        f"<tr>"
        f'<th scope="row">{slug_cell}</th>'
        f"{cells_html}"
        f'<td class="owner">{owner_cell}</td>'
        f'<td class="summary">{summary_cell}</td>'
        f"</tr>"
    )


def _render_legend() -> str:
    items = []
    for tone, label in (
        ("green", "green = pass / healthy / <=7d"),
        ("yellow", "yellow = warn / <=30d / review needed"),
        ("red", "red = fail / >30d / unreachable"),
        ("grey", "grey = unknown / skipped / n/a"),
    ):
        items.append(
            f'<li><span class="dot" style="background:{TONE_COLOR[tone]}"></span>'
            f"{html.escape(label)}</li>"
        )
    return '<ul class="legend">' + "".join(items) + "</ul>"


def render_html(rows: list[ThemeRow]) -> str:
    stamp = docs_assets_cache_stamp()
    # Deliberately NO "generated at <now>" timestamp: the file is auto-
    # committed from CI, so letting the rendered HTML float with every
    # run would drown real content drift in clock noise and break the
    # `--check` mode used by pre-commit. The git log on docs/themes/
    # index.html answers "when was this last refreshed".
    head_cells = "".join(f"<th>{html.escape(label)}</th>" for _, label in COLUMNS)
    body_rows = "\n".join(_render_row(r) for r in rows)
    total = len(rows)
    by_stage: dict[str, int] = {}
    for r in rows:
        by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
    stage_summary_parts = [
        f"{n} {html.escape(stage)}" for stage, n in sorted(by_stage.items())
    ]
    stage_summary = " · ".join(stage_summary_parts) if stage_summary_parts else "0 themes"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Theme status -- fifty</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="../assets/style.css?v={html.escape(stamp)}">
<style>
body {{ max-width: 1280px; margin: 0 auto; padding: 2rem 1rem 4rem; }}
h1 {{ margin-bottom: 0.25rem; }}
.meta {{ color: #555; font-size: 0.9rem; margin-bottom: 1.5rem; }}
.legend {{ list-style: none; padding: 0; margin: 0 0 1.5rem; display: flex; gap: 1.25rem; flex-wrap: wrap; font-size: 0.85rem; }}
.legend li {{ display: inline-flex; align-items: center; gap: 0.4rem; }}
.dot {{ display: inline-block; width: 0.7rem; height: 0.7rem; border-radius: 50%; }}
table.status {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
table.status th, table.status td {{ padding: 0.45rem 0.55rem; border-bottom: 1px solid #ddd; text-align: left; vertical-align: top; }}
table.status thead th {{ background: #f5f5f3; font-weight: 600; }}
table.status th[scope="row"] {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; }}
td.cell {{ white-space: nowrap; }}
td.cell .dot {{ margin-right: 0.35rem; vertical-align: middle; }}
td.cell .label {{ font-size: 0.85rem; text-transform: none; }}
td.summary {{ color: #555; font-size: 0.85rem; max-width: 320px; }}
td.owner {{ color: #555; font-size: 0.85rem; }}
tr:hover td, tr:hover th[scope="row"] {{ background: #fafaf7; }}
a {{ color: #2a5aa3; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>Theme status</h1>
<p class="meta">
{total} theme{'s' if total != 1 else ''} ({html.escape(stage_summary)}) ·
auto-regenerated by <code>bin/build-theme-status.py</code> after every check.yml run.
</p>
{_render_legend()}
<table class="status">
<thead>
<tr>
<th>Theme</th>
{head_cells}
<th>Owner</th>
<th>Summary</th>
</tr>
</thead>
<tbody>
{body_rows}
</tbody>
</table>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Don't write; exit 1 if docs/themes/index.html is stale.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_PATH,
        help="Destination path (default: docs/themes/index.html).",
    )
    args = parser.parse_args(argv)

    rows = collect_rows()
    html_text = render_html(rows)

    if args.check:
        if not args.out.is_file():
            print(f"{args.out} is missing. Run: python3 bin/build-theme-status.py", file=sys.stderr)
            return 1
        current = args.out.read_text(encoding="utf-8")
        if current != html_text:
            print(
                f"{args.out} is out of date. Run: python3 bin/build-theme-status.py",
                file=sys.stderr,
            )
            return 1
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_text, encoding="utf-8")
    print(f"wrote {args.out} ({len(rows)} theme(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
