#!/usr/bin/env python3
"""Generate the visual-regression fixture set used to validate the smart
design agent's vision reviewer.

Why this exists
---------------
`bin/snap-vision-review.py` calls a vision model and writes `vision:*`
findings into `findings.json`. To trust those findings, we need a labelled
test set: known-bad images that the reviewer MUST flag, and known-good-but-
unusual images that the reviewer MUST NOT flag (false-positive bait).

We could collect such a set by snapshotting real broken / well-designed pages
and hand-curating, but that ties the fixture set to a moving theme codebase
and makes regressions hard to attribute. Instead this script renders 10
synthetic images deterministically with PIL. Re-running this script with the
same Pillow version produces byte-identical PNGs, so the fixture set is
reproducible and the vision-review precision/recall numbers in CI mean
something stable.

Layout
------
The fixtures live next to a `manifest.json` in the same directory. The
manifest declares, per fixture, which `vision:*` finding kinds the reviewer
SHOULD return ("expected_findings") and which it MUST NOT return
("forbidden_findings"). `bin/snap-vision-review.py --validate <fixtures-dir>`
loads that manifest and computes precision/recall against it.

Regenerating
------------
    python3 tests/fixtures/visual-regressions/_generator.py

Commit the resulting PNGs along with any change to this script.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Synthetic 1280x800 viewport — same shape as snap.py's desktop viewport so
# the reviewer sees images at the size it would see real screenshots at.
W, H = 1280, 800

FIXTURE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Font helpers — fall back to PIL default if system fonts unavailable
# ---------------------------------------------------------------------------

def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Best-effort font loader. We try a few system locations; if none of them
    work we use PIL's bitmap default. Determinism comes from the seed image
    content + this lookup order, not from a specific font being present.
    """
    candidates = (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    )
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _new(bg: tuple[int, int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), bg)
    return img, ImageDraw.Draw(img)


def _text(draw: ImageDraw.ImageDraw, xy, text: str, *, size: int, fill: tuple[int, int, int]) -> None:
    draw.text(xy, text, fill=fill, font=_load_font(size))


# ---------------------------------------------------------------------------
# Planted regressions (5) — reviewer MUST flag these
# ---------------------------------------------------------------------------

def make_regression_typography_overpowered() -> Image.Image:
    """A single 'WELCOME!' headline at 320pt consuming most of the viewport,
    no body content, no CTA. Should fire vision:typography-overpowered.
    """
    img, d = _new((250, 246, 238))
    _text(d, (60, 200), "WELCOME!", size=320, fill=(20, 20, 20))
    _text(d, (60, 720), "browse", size=14, fill=(160, 160, 160))
    return img


def make_regression_hierarchy_flat() -> Image.Image:
    """All headings + body at the same 24px size, no weight contrast,
    no spacing rhythm. Should fire vision:hierarchy-flat.
    """
    img, d = _new((255, 255, 255))
    rows = [
        "Page Title Goes Here",
        "Section Heading One",
        "Subsection two",
        "Body copy paragraph that explains things in detail.",
        "Another body paragraph following on from the previous one.",
        "Section Heading Two",
        "More body copy, again same size, again same weight, no rhythm.",
        "Subsection three",
        "Body copy continues at exactly the same size as everything else.",
        "Section Heading Three",
        "And the page just keeps going at one constant typographic level.",
    ]
    y = 80
    for row in rows:
        _text(d, (80, y), row, size=24, fill=(40, 40, 40))
        y += 50
    return img


def make_regression_cta_buried() -> Image.Image:
    """Page is 90% body text. The only CTA ('shop') is rendered at 12pt
    light gray at the very bottom edge. Should fire vision:cta-buried.
    """
    img, d = _new((255, 255, 255))
    _text(d, (80, 60), "ABOUT US", size=42, fill=(20, 20, 20))
    body = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do "
        "eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut "
        "enim ad minim veniam, quis nostrud exercitation ullamco laboris "
        "nisi ut aliquip ex ea commodo consequat."
    )
    y = 140
    for _ in range(8):
        _text(d, (80, y), body, size=18, fill=(60, 60, 60))
        y += 70
    _text(d, (1180, 770), "shop", size=12, fill=(180, 180, 180))
    return img


def make_regression_color_clash() -> Image.Image:
    """Warm-cream selvedge-like palette page with three bright saturated
    cyan + magenta blocks scattered through it. Should fire vision:color-clash
    (or vision:brand-violation if intent.md is in scope).
    """
    img, d = _new((245, 240, 230))
    _text(d, (80, 60), "Selvedge Workshop", size=44, fill=(60, 40, 25))
    _text(d, (80, 130), "Hand-finished denim, small batches.", size=22, fill=(110, 80, 55))
    d.rectangle((80, 200, 380, 340), fill=(0, 220, 230))
    d.rectangle((420, 200, 720, 340), fill=(220, 30, 200))
    d.rectangle((760, 200, 1060, 340), fill=(60, 255, 80))
    _text(d, (80, 380), "Latest from the workshop", size=26, fill=(60, 40, 25))
    _text(d, (80, 430), "Notes from the cutting floor.", size=18, fill=(110, 80, 55))
    return img


def make_regression_whitespace_imbalance() -> Image.Image:
    """Tiny content block in upper-left corner, ~85% of the viewport empty.
    Should fire vision:whitespace-imbalance (too much void, no media).
    """
    img, d = _new((255, 255, 255))
    _text(d, (60, 60), "Hello.", size=32, fill=(40, 40, 40))
    _text(d, (60, 110), "We make things.", size=14, fill=(120, 120, 120))
    return img


# ---------------------------------------------------------------------------
# Well-designed-unusual (5) — reviewer MUST NOT flag these
# ---------------------------------------------------------------------------

def make_welldesigned_deliberate_whitespace() -> Image.Image:
    """Editorial pacing: tight type block in the upper third, generous
    intentional whitespace below. Mimics lysholm's restrained voice. The
    whitespace is the design, not a bug. Reviewer must NOT fire
    whitespace-imbalance OR cta-buried.
    """
    img, d = _new((247, 245, 241))
    _text(d, (120, 120), "Spring 2026", size=14, fill=(140, 130, 110))
    _text(d, (120, 150), "A quiet collection,", size=56, fill=(60, 50, 40))
    _text(d, (120, 220), "made slowly.", size=56, fill=(60, 50, 40))
    _text(d, (120, 320), "Shop the lookbook  \u2192", size=18, fill=(180, 80, 50))
    return img


def make_welldesigned_large_display_hero() -> Image.Image:
    """Intentional large display type, but bounded, with clear navigation
    above it and a CTA + supporting copy below. The display IS dominant but
    the page still has hierarchy + a clear next action. Reviewer must NOT
    fire typography-overpowered or hierarchy-flat.
    """
    img, d = _new((255, 255, 255))
    _text(d, (40, 30), "shop   journal   about   bag", size=14, fill=(60, 60, 60))
    _text(d, (60, 140), "MAKE", size=180, fill=(20, 20, 20))
    _text(d, (60, 320), "GOOD", size=180, fill=(220, 70, 50))
    _text(d, (60, 500), "THINGS.", size=180, fill=(20, 20, 20))
    d.rectangle((60, 700, 260, 760), fill=(20, 20, 20))
    _text(d, (95, 716), "shop the goods", size=18, fill=(255, 255, 255))
    return img


def make_welldesigned_monochrome_restraint() -> Image.Image:
    """Intentional monochrome palette (warm gray scale only). Looks unusual
    next to colorful themes, but it's a coherent design choice with clear
    hierarchy and CTA. Reviewer must NOT fire color-clash or
    brand-violation.
    """
    img, d = _new((240, 238, 234))
    _text(d, (80, 60), "Atelier", size=42, fill=(40, 38, 34))
    _text(d, (80, 130), "Notebook  \u00b7  Catalogue  \u00b7  Visit", size=14, fill=(110, 105, 95))
    d.rectangle((80, 200, 600, 560), fill=(220, 218, 213))
    d.rectangle((640, 200, 1200, 380), fill=(200, 196, 188))
    d.rectangle((640, 400, 1200, 560), fill=(180, 176, 168))
    _text(d, (80, 600), "Latest field notes.", size=18, fill=(80, 76, 70))
    _text(d, (80, 640), "Read all  \u2192", size=16, fill=(40, 38, 34))
    return img


def make_welldesigned_asymmetric_layout() -> Image.Image:
    """Off-center hero with deliberate empty space on the right. Looks
    unusual but is a confident editorial layout choice. Reviewer must NOT
    fire alignment-off or whitespace-imbalance.
    """
    img, d = _new((250, 248, 245))
    d.rectangle((0, 0, 600, H), fill=(20, 20, 20))
    _text(d, (40, 60), "AERO", size=22, fill=(245, 240, 250))
    _text(d, (40, 280), "Spring", size=72, fill=(245, 240, 250))
    _text(d, (40, 360), "Drop", size=72, fill=(190, 160, 230))
    _text(d, (40, 480), "Fourteen new pieces.", size=16, fill=(200, 195, 200))
    _text(d, (40, 510), "Shop now  \u2192", size=18, fill=(245, 240, 250))
    _text(d, (700, 60), "01 / 14", size=14, fill=(120, 110, 130))
    _text(d, (700, 720), "Aero  \u00b7  Spring 2026", size=12, fill=(120, 110, 130))
    return img


def make_welldesigned_editorial_magazine() -> Image.Image:
    """Magazine layout: pull quote, sized hierarchy, photo placeholder,
    multiple typographic levels in deliberate rhythm. Reviewer must NOT
    fire hierarchy-flat or typography-overpowered.
    """
    img, d = _new((253, 251, 247))
    _text(d, (80, 50), "JOURNAL", size=12, fill=(140, 130, 115))
    _text(d, (80, 90), "On the cutting floor", size=44, fill=(40, 30, 22))
    _text(d, (80, 160), "An afternoon with the makers, March 2026.", size=16, fill=(110, 100, 88))
    d.rectangle((80, 220, 660, 560), fill=(220, 215, 205))
    _text(d, (700, 220), '\u201cThe table is older than', size=28, fill=(40, 30, 22))
    _text(d, (700, 260), 'any of us. It remembers', size=28, fill=(40, 30, 22))
    _text(d, (700, 300), 'every cut.\u201d', size=28, fill=(40, 30, 22))
    _text(d, (700, 360), "\u2014 K. Lindahl, head cutter", size=14, fill=(140, 130, 115))
    _text(d, (700, 430), "Read the full piece  \u2192", size=16, fill=(180, 80, 50))
    return img


# ---------------------------------------------------------------------------
# Manifest + driver
# ---------------------------------------------------------------------------

FIXTURES = [
    # (filename, generator, expected_findings, forbidden_findings, severity_floor, notes)
    (
        "regression-typography-overpowered.png",
        make_regression_typography_overpowered,
        ["vision:typography-overpowered"],
        [],
        "error",
        "Single 320pt headline consuming the whole viewport, no body, no CTA.",
    ),
    (
        "regression-hierarchy-flat.png",
        make_regression_hierarchy_flat,
        ["vision:hierarchy-flat"],
        [],
        "error",
        "All text at the same 24pt size, no weight or spacing rhythm.",
    ),
    (
        "regression-cta-buried.png",
        make_regression_cta_buried,
        ["vision:cta-buried"],
        [],
        "error",
        "Eight blocks of body copy, only CTA is 12pt gray text in the bottom-right corner.",
    ),
    (
        "regression-color-clash.png",
        make_regression_color_clash,
        ["vision:color-clash", "vision:brand-violation"],
        [],
        "warn",
        "Warm-cream selvedge-style palette with three saturated cyan/magenta/green blocks. Either color-clash OR brand-violation is acceptable.",
    ),
    (
        "regression-whitespace-imbalance.png",
        make_regression_whitespace_imbalance,
        ["vision:whitespace-imbalance"],
        [],
        "error",
        "Tiny content block in upper-left, ~85% of viewport empty white space.",
    ),
    (
        "welldesigned-deliberate-whitespace.png",
        make_welldesigned_deliberate_whitespace,
        [],
        ["vision:whitespace-imbalance", "vision:cta-buried"],
        None,
        "Editorial pacing with intentional whitespace and a small but visible CTA.",
    ),
    (
        "welldesigned-large-display-hero.png",
        make_welldesigned_large_display_hero,
        [],
        ["vision:typography-overpowered", "vision:hierarchy-flat"],
        None,
        "Large display type used deliberately with navigation, hierarchy, and a CTA below.",
    ),
    (
        "welldesigned-monochrome-restraint.png",
        make_welldesigned_monochrome_restraint,
        [],
        ["vision:color-clash", "vision:brand-violation"],
        None,
        "Intentional monochrome warm-gray palette with clear hierarchy.",
    ),
    (
        "welldesigned-asymmetric-layout.png",
        make_welldesigned_asymmetric_layout,
        [],
        ["vision:alignment-off", "vision:whitespace-imbalance"],
        None,
        "Off-center hero with deliberate empty space; confident editorial layout.",
    ),
    (
        "welldesigned-editorial-magazine.png",
        make_welldesigned_editorial_magazine,
        [],
        ["vision:hierarchy-flat", "vision:typography-overpowered"],
        None,
        "Magazine layout with photo, pull quote, and multiple typographic levels in rhythm.",
    ),
]


def main() -> int:
    manifest = {
        "_meta": {
            "purpose": (
                "Labelled fixture set for bin/snap-vision-review.py. Each "
                "PNG declares which vision:* findings the reviewer must "
                "return (expected_findings) and which it must NOT return "
                "(forbidden_findings). Used by --validate mode to compute "
                "precision/recall."
            ),
            "viewport": {"width": W, "height": H},
            "generator": "tests/fixtures/visual-regressions/_generator.py",
            "regen_command": "python3 tests/fixtures/visual-regressions/_generator.py",
            "acceptance": {
                "regressions_caught_min": 4,
                "regressions_total": 5,
                "well_designed_false_positives_max": 1,
                "well_designed_total": 5,
                "precision_min": 0.80,
                "recall_min": 0.70,
            },
        },
        "fixtures": [],
    }
    for filename, generator, expected, forbidden, severity_floor, notes in FIXTURES:
        out = FIXTURE_DIR / filename
        img = generator()
        img.save(out, format="PNG", optimize=True)
        manifest["fixtures"].append(
            {
                "file": filename,
                "kind": "regression" if filename.startswith("regression-") else "well-designed",
                "expected_findings": expected,
                "forbidden_findings": forbidden,
                "severity_floor": severity_floor,
                "notes": notes,
            }
        )
        print(f"wrote {filename}  ({out.stat().st_size:,} bytes)")
    manifest_path = FIXTURE_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {manifest_path.name}  ({len(manifest['fixtures'])} fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
