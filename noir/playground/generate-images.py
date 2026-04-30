#!/usr/bin/env python3
"""Generate Selvedge-style 800x800 hero placeholder images for every
journal post and page that the Playground demo exposes.

Selvedge brief (from .cursor/rules/playground-imagery.mdc):

  Palette       base #160F08 (near-black warm brown)
                contrast #EDE3CE (cream)
                accent #D06030 (rust / terracotta)
  Lighting      single dramatic side-light from upper-left;
                long shadows; fine-art moody
  Type          cream serif (Iowan Old Style / Playfair),
                italic for display
  Feel          dark editorial menswear / workwear catalogue;
                refined and cinematic

The output is a procedural typographic card -- not a faked photograph.
Each card has:

  * a warm radial light from the upper-left over the brown base,
  * a subtle film-grain noise pass so the card never reads as flat
    digital fill,
  * a thin rust-orange divider rule at top-center,
  * a small uppercase tracked-out kicker (post date placeholder /
    page section label),
  * a large centered serif title (italic display weight) wrapped to fit,
  * a small "Selvedge --- since '26" footer mark in cream,

and is saved at 800x800 PNG into the same `images/` folder this script
lives in. Output filenames intentionally mirror the obel post/page
hero filenames so the seeder picks them up without any blueprint
edits.

Run with:

    python3 selvedge/playground/generate-images.py

Idempotent; overwrites previous outputs.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ------------------------------------------------------------------ palette
BASE = (22, 15, 8)        # #160F08 near-black warm brown
WARM_LIGHT = (60, 38, 22) # upper-left side light tint
CREAM = (237, 227, 206)   # #EDE3CE
RUST = (208, 96, 48)      # #D06030 accent
INK = (12, 8, 4)          # deepest shadow

OUT_DIR = Path(__file__).parent / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 800
MARGIN = 64

# ------------------------------------------------------------------ fonts
# Selvedge's display stack starts with Playfair Display, then Iowan Old
# Style. Pillow can't load woff2 (only the woff2 file ships in
# selvedge/assets/fonts), so we fall back to the macOS-bundled Iowan,
# then Big Caslon, Bodoni, Palatino, Georgia. All four are visually
# in-family for the dark-editorial mood we're after.
SERIF_CANDIDATES = [
    # path, ttc-index, italic?
    ("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 1, True),   # Italic
    ("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 0, False),  # Roman
    ("/System/Library/Fonts/Supplemental/Big Caslon.ttf", 0, False),
    ("/System/Library/Fonts/Supplemental/Bodoni 72.ttc", 1, True),
    ("/System/Library/Fonts/Palatino.ttc", 2, True),
    ("/System/Library/Fonts/Supplemental/Georgia Italic.ttf", 0, True),
    ("/System/Library/Fonts/Supplemental/PTSerif.ttc", 1, True),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 0, False),
]

SANS_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(path: str, size: int, index: int = 0):
    try:
        if path.endswith(".ttc"):
            return ImageFont.truetype(path, size, index=index)
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return None


def best_serif(size: int, prefer_italic: bool = True):
    """Return a serif PIL font at requested px-size. Prefers italic
    (matches selvedge's display weight) when available."""
    candidates = SERIF_CANDIDATES
    if not prefer_italic:
        candidates = sorted(candidates, key=lambda c: c[2])
    for path, idx, _italic in candidates:
        if not os.path.exists(path):
            continue
        font = _load_font(path, size, idx)
        if font is not None:
            return font
    return ImageFont.load_default()


def best_sans(size: int):
    for path in SANS_CANDIDATES:
        if not os.path.exists(path):
            continue
        font = _load_font(path, size)
        if font is not None:
            return font
    return ImageFont.load_default()


# ------------------------------------------------------------------ painting
def _radial_gradient(size: int, center: tuple[int, int],
                     inner: tuple[int, int, int],
                     outer: tuple[int, int, int],
                     radius: int) -> Image.Image:
    """Cheap painter-style radial gradient. Returns RGB image."""
    img = Image.new("RGB", (size, size), outer)
    px = img.load()
    cx, cy = center
    inv_r = 1.0 / max(radius, 1)
    for y in range(size):
        dy = (y - cy)
        for x in range(size):
            dx = (x - cx)
            t = min(1.0, math.sqrt(dx * dx + dy * dy) * inv_r)
            # smoothstep so the falloff feels lit, not flashlight-y
            t = t * t * (3 - 2 * t)
            r = int(inner[0] + (outer[0] - inner[0]) * t)
            g = int(inner[1] + (outer[1] - inner[1]) * t)
            b = int(inner[2] + (outer[2] - inner[2]) * t)
            px[x, y] = (r, g, b)
    return img


def _add_grain(img: Image.Image, amount: int = 7, seed: int = 0) -> Image.Image:
    """Add per-pixel low-amplitude noise (film grain) to break up the
    digital fill. Deterministic per seed so we can keep regen stable."""
    rng = random.Random(seed)
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            n = rng.randint(-amount, amount)
            r, g, b = px[x, y]
            px[x, y] = (
                max(0, min(255, r + n)),
                max(0, min(255, g + n)),
                max(0, min(255, b + n)),
            )
    return img


def _wrap_text(draw: ImageDraw.ImageDraw, text: str,
               font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for w in words:
        candidate = " ".join(current + [w])
        bb = draw.textbbox((0, 0), candidate, font=font)
        if bb[2] - bb[0] > max_w and current:
            lines.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_centered_lines(draw: ImageDraw.ImageDraw, lines: list[str],
                          font: ImageFont.FreeTypeFont,
                          y_center: int, fill, line_gap: int = 8) -> None:
    metrics = [
        draw.textbbox((0, 0), ln, font=font) for ln in lines
    ]
    heights = [bb[3] - bb[1] for bb in metrics]
    widths = [bb[2] - bb[0] for bb in metrics]
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = y_center - total_h // 2
    for ln, w_, h_, bb in zip(lines, widths, heights, metrics):
        x = (SIZE - w_) // 2 - bb[0]
        draw.text((x, y - bb[1]), ln, font=font, fill=fill)
        y += h_ + line_gap


# ------------------------------------------------------------------ card
def make_image(slug: str, label: str, kicker: str, seed_offset: int = 0) -> None:
    """Build one editorial card. `slug` -> filename, `label` -> title,
    `kicker` -> small tracked-out line above the title."""
    seed = abs(hash(slug)) % (2**31) + seed_offset

    # 1. warm side-lit gradient base
    img = _radial_gradient(
        SIZE,
        center=(int(SIZE * 0.18), int(SIZE * 0.22)),
        inner=WARM_LIGHT,
        outer=BASE,
        radius=int(SIZE * 0.95),
    )
    # add a subtle deep-shadow vignette on the lower-right
    shadow = _radial_gradient(
        SIZE,
        center=(int(SIZE * 0.92), int(SIZE * 0.92)),
        inner=BASE,
        outer=INK,
        radius=int(SIZE * 0.85),
    )
    img = Image.blend(img, shadow, 0.35)

    # 2. film grain so it never reads as flat digital fill
    img = _add_grain(img, amount=6, seed=seed)

    # 3. faint outer frame in cream (like a printed plate edge)
    draw = ImageDraw.Draw(img, "RGBA")
    frame_inset = 30
    draw.rectangle(
        [frame_inset, frame_inset, SIZE - frame_inset - 1, SIZE - frame_inset - 1],
        outline=(*CREAM, 28),
        width=1,
    )

    # 4. top-center rust rule + small motif (vary the motif per card so
    # 36 cards don't look identical at a glance)
    rule_y = int(SIZE * 0.30)
    rule_w = 110
    rule_x0 = (SIZE - rule_w) // 2
    draw.rectangle(
        [rule_x0, rule_y, rule_x0 + rule_w, rule_y + 2],
        fill=RUST,
    )
    motifs = [_motif_dot, _motif_diamond, _motif_bracket, _motif_circle]
    motifs[seed % len(motifs)](draw, SIZE // 2, rule_y + 22)

    # 5. kicker line (small tracked-out cream caps)
    kicker_font = best_sans(15)
    kicker_text = _track(kicker.upper(), 4)
    kbb = draw.textbbox((0, 0), kicker_text, font=kicker_font)
    kx = (SIZE - (kbb[2] - kbb[0])) // 2 - kbb[0]
    ky = rule_y - 28
    draw.text((kx, ky), kicker_text, font=kicker_font, fill=(*CREAM, 200))

    # 6. centered serif title -- shrink to fit, italic for display feel
    max_w = SIZE - MARGIN * 2 - 24
    title_y = int(SIZE * 0.56)
    chosen_size = 64
    chosen_lines: list[str] = []
    chosen_font: ImageFont.FreeTypeFont | None = None
    for trial in (64, 56, 48, 42, 36, 30, 26, 22):
        font_try = best_serif(trial, prefer_italic=True)
        lines_try = _wrap_text(draw, label, font_try, max_w)
        if len(lines_try) <= 5:
            chosen_size = trial
            chosen_font = font_try
            chosen_lines = lines_try
            if trial >= 42 or len(lines_try) <= 3:
                break
    if chosen_font is None:
        chosen_font = best_serif(30, prefer_italic=True)
        chosen_lines = _wrap_text(draw, label, chosen_font, max_w)

    _draw_centered_lines(
        draw, chosen_lines, chosen_font,
        y_center=title_y, fill=CREAM,
        line_gap=int(chosen_size * 0.16),
    )

    # 7. footer mark "SELVEDGE — SINCE '26"
    mark_font = best_sans(12)
    mark_text = _track("SELVEDGE   \u00b7   SINCE '26", 3)
    mbb = draw.textbbox((0, 0), mark_text, font=mark_font)
    mx = (SIZE - (mbb[2] - mbb[0])) // 2 - mbb[0]
    my = SIZE - frame_inset - 28
    draw.text((mx, my), mark_text, font=mark_font, fill=(*RUST, 220))

    # final soft blur on the gradient layer would soften too much --
    # instead, a tiny global posterise is skipped; the grain is enough.
    img = img.convert("RGB")
    out = OUT_DIR / f"{slug}.png"
    img.save(out, "PNG", optimize=True)
    print(f"  ok  {out.name}")


def _track(s: str, px: int) -> str:
    """Cheap visual letter-spacing -- pad each character with hair-spaces."""
    spacer = " " * (px // 4 + 1)
    return spacer.join(s)


# ------------------------------------------------------------------ motifs
def _motif_dot(draw, cx: int, cy: int) -> None:
    r = 3
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RUST)


def _motif_diamond(draw, cx: int, cy: int) -> None:
    r = 5
    draw.polygon(
        [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
        outline=RUST,
        width=1,
    )


def _motif_bracket(draw, cx: int, cy: int) -> None:
    w, h = 12, 6
    draw.line([(cx - w, cy + h), (cx - w, cy), (cx + w, cy), (cx + w, cy + h)],
              fill=RUST, width=1)


def _motif_circle(draw, cx: int, cy: int) -> None:
    r = 6
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RUST, width=1)


# ------------------------------------------------------------------ manifest
# Each entry: (slug, human title, kicker line)
# Kicker lines are intentionally varied so the 36 cards don't all read
# "JOURNAL"; we give posts a faux-date kicker and pages a section label.
POSTS: list[tuple[str, str, str]] = [
    ("wonders-post-behind-the-scenes-bottling-mondays",
     "Behind the Scenes: Bottling Mondays", "VOL II  No 03"),
    ("wonders-post-caring-for-your-portable-hole",
     "Caring for Your Portable Hole", "FIELD GUIDE"),
    ("wonders-post-carl-on-the-moon",
     "Carl on the Moon", "DISPATCH"),
    ("wonders-post-chaos-seasoning-recipe-roundup",
     "Chaos Seasoning Recipe Roundup", "FROM THE PANTRY"),
    ("wonders-post-fog-season",
     "Fog Season", "ALMANAC"),
    ("wonders-post-forbidden-honey-what-does-forbidden-mean",
     "What Does Forbidden Mean?", "ESSAY"),
    ("wonders-post-hidden-gems-5-overlooked-products",
     "Hidden Gems: Five Overlooked Wares", "EDITORS' PICKS"),
    ("wonders-post-how-to-apply-existential-dread-repellent",
     "How to Apply Dread Repellent", "FIELD GUIDE"),
    ("wonders-post-imaginary-ownership-beginners",
     "Imaginary Ownership for Beginners", "PRIMER"),
    ("wonders-post-interview-with-carl",
     "Interview with Carl", "INTERVIEW"),
    ("wonders-post-invisible-umbrella-spotlight",
     "Invisible Umbrella Spotlight", "PRODUCT NOTE"),
    ("wonders-post-memoirs-of-a-left-sock",
     "Memoirs of a Left Sock", "MEMOIR"),
    ("wonders-post-mildly-haunted-candle-faq",
     "Mildly Haunted Candle FAQ", "FAQ"),
    ("wonders-post-philosophy-of-bottled-monday-morning",
     "Philosophy of Bottled Monday Morning", "ESSAY"),
    ("wonders-post-pocket-thunder-safety",
     "Pocket Thunder Safety", "SAFETY NOTE"),
    ("wonders-post-spare-tuesday-field-guide",
     "Spare Tuesday Field Guide", "FIELD GUIDE"),
    ("wonders-post-tangible-wifi-30-day-review",
     "Tangible WiFi: 30-Day Review", "REVIEW"),
    ("wonders-post-the-art-of-artisanal-silence",
     "The Art of Artisanal Silence", "ESSAY"),
    ("wonders-post-welcome-to-wonders-and-oddities",
     "Welcome to Wonders & Oddities", "FIRST DISPATCH"),
    ("wonders-post-year-one-abridged",
     "Year One, Abridged", "ANNUAL REVIEW"),
]

PAGES: list[tuple[str, str, str]] = [
    ("wonders-page-about", "About the Shop", "INTRODUCTION"),
    ("wonders-page-contact", "Find the Shop", "CONTACT"),
    ("wonders-page-faq", "Frequently Asked", "POLICIES"),
    ("wonders-page-home", "Welcome", "HOME"),
    ("wonders-page-journal", "From the Workbench", "JOURNAL"),
    ("wonders-page-lookbook", "The Lookbook", "EDITORIAL"),
    ("wonders-page-privacy-policy", "Privacy Policy", "POLICY"),
    ("wonders-page-shipping-returns", "Shipping & Returns", "POLICIES"),
]


def main() -> int:
    items = POSTS + PAGES
    print(f"Generating {len(items)} Selvedge hero cards into {OUT_DIR}/")
    for slug, label, kicker in items:
        make_image(slug, label, kicker)
    print(f"\nDone. {len(items)} hero cards written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
