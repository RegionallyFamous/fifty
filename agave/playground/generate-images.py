#!/usr/bin/env python3
"""Generate Obel-style 800x800 hero placeholder cards for every
journal post and page.

Obel brief (from .cursor/rules/playground-imagery.mdc):

  Light Scandinavian minimal: off-white base #FAFAF7, terracotta
  accent #C07241, deep ink contrast #1A1A1A. Soft natural marble /
  linen / pale-wood surfaces. Diffuse north-facing daylight. One or
  two contextual props max. Generous white space. Cream card stock
  in a fine serif; terracotta ink or ribbon accent. Quiet, confident,
  design-museum catalogue feel.

Procedural translation:

  * Off-white base with a barely-visible warm wash from the upper-
    right (the "north window" light direction is reversed here so
    no two themes use the same lighting axis -- selvedge from
    upper-left, lysholm from upper-left, obel from upper-right).
  * Faint paper-grain pass.
  * One terracotta detail per card -- ribbon, bracket, or small
    rule -- placed off-axis with negative space around it.
  * Centered serif title (Iowan Old Style Roman, deep ink) at the
    visual third.
  * Small uppercase tracked-out kicker line above the title in
    terracotta.
  * "OBEL // Vol. I" footer mark in soft ink.

Output filenames mirror the existing obel hero filenames so the
seeder picks them up without any blueprint edits. Idempotent.

This generator is the matching pattern to chonk/, selvedge/,
aero/, and lysholm/ -- one generate-images.py per theme, each in
its own visual voice. The check `check_hero_images_unique_across_themes`
in bin/check.py guarantees the four sets stay distinct.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ palette
OFFWHITE = (250, 250, 247)   # base #FAFAF7
SURFACE = (255, 255, 255)    # surface #FFFFFF
PAPER = (242, 241, 236)      # subtle #F2F1EC
TERRA = (192, 114, 65)       # accent #C07241
INK = (26, 26, 26)           # contrast #1A1A1A
SOFT_INK = (90, 87, 79)      # secondary #5A574F

OUT_DIR = Path(__file__).parent / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 800

# ------------------------------------------------------------------ fonts
SERIF_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 1),
    ("/System/Library/Fonts/Palatino.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Big Caslon.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Bodoni 72.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 0),
]

SANS_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(path, size, index=0):
    try:
        if path.endswith(".ttc"):
            return ImageFont.truetype(path, size, index=index)
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return None


def best_serif(size):
    for path, idx in SERIF_CANDIDATES:
        if not os.path.exists(path):
            continue
        f = _load_font(path, size, idx)
        if f is not None:
            return f
    return ImageFont.load_default()


def best_sans(size):
    for path in SANS_CANDIDATES:
        if not os.path.exists(path):
            continue
        f = _load_font(path, size)
        if f is not None:
            return f
    return ImageFont.load_default()


# ------------------------------------------------------------------ painters
def _warm_wash():
    """Warm wash from upper-RIGHT (obel's lighting axis); selvedge and
    lysholm both light from upper-left, so this keeps the four
    procedural sets visually distinguishable at a glance."""
    img = Image.new("RGB", (SIZE, SIZE), OFFWHITE)
    px = img.load()
    cx, cy = int(SIZE * 0.85), int(SIZE * 0.18)
    inv_r = 1.0 / (SIZE * 0.95)
    for y in range(SIZE):
        for x in range(SIZE):
            dx, dy = x - cx, y - cy
            t = min(1.0, math.sqrt(dx * dx + dy * dy) * inv_r)
            t = t * t * (3 - 2 * t)
            r = int(SURFACE[0] + (PAPER[0] - SURFACE[0]) * t)
            g = int(SURFACE[1] + (PAPER[1] - SURFACE[1]) * t)
            b = int(SURFACE[2] + (PAPER[2] - SURFACE[2]) * t)
            px[x, y] = (r, g, b)
    return img


def _grain(img, amount=3, seed=0):
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


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], []
    for w in words:
        cand = " ".join(cur + [w])
        bb = draw.textbbox((0, 0), cand, font=font)
        if bb[2] - bb[0] > max_w and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def _draw_centered(draw, lines, font, y_center, fill, line_gap):
    metrics = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    heights = [bb[3] - bb[1] for bb in metrics]
    widths = [bb[2] - bb[0] for bb in metrics]
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = y_center - total_h // 2
    for ln, w_, h_, bb in zip(lines, widths, heights, metrics):
        x = (SIZE - w_) // 2 - bb[0]
        draw.text((x, y - bb[1]), ln, font=font, fill=fill)
        y += h_ + line_gap


def _track(s, n):
    return (" " * (n // 4 + 1)).join(s)


# ------------------------------------------------------------------ details
def _detail_ribbon(draw, seed):
    """Vertical terracotta ribbon down the right margin."""
    rng = random.Random(seed)
    x = rng.choice([60, SIZE - 80])
    y0, y1 = 80, SIZE - 120
    draw.rectangle([x, y0, x + 4, y1], fill=TERRA)


def _detail_bracket(draw, seed):
    """Small terracotta corner bracket at top-left."""
    rng = random.Random(seed)
    x, y = rng.randint(60, 100), rng.randint(60, 100)
    s = 28
    draw.line([(x, y), (x + s, y)], fill=TERRA, width=2)
    draw.line([(x, y), (x, y + s)], fill=TERRA, width=2)


def _detail_rule(draw, seed):
    """Short horizontal terracotta rule, off-axis."""
    rng = random.Random(seed)
    x = rng.randint(80, SIZE - 200)
    y = rng.randint(120, 200)
    w = rng.randint(60, 120)
    draw.rectangle([x, y, x + w, y + 2], fill=TERRA)


DETAILS = [_detail_ribbon, _detail_bracket, _detail_rule]


# ------------------------------------------------------------------ card
def make_image(slug, label, kicker):
    seed = abs(hash(slug)) % (2**31)
    img = _warm_wash()
    img = _grain(img, amount=3, seed=seed)
    draw = ImageDraw.Draw(img, "RGBA")

    # rotate detail per slug
    DETAILS[seed % len(DETAILS)](draw, seed)

    # kicker (small terracotta caps, tracked)
    kicker_font = best_sans(13)
    kt = _track(kicker.upper(), 5)
    kbb = draw.textbbox((0, 0), kt, font=kicker_font)
    kx = (SIZE - (kbb[2] - kbb[0])) // 2 - kbb[0]
    ky = int(SIZE * 0.36)
    draw.text((kx, ky), kt, font=kicker_font, fill=TERRA)

    # title -- serif, deep ink
    max_w = SIZE - 160
    chosen, chosen_lines = None, []
    for trial in (62, 54, 46, 40, 34, 28, 24):
        f = best_serif(trial)
        ls = _wrap(draw, label, f, max_w)
        if len(ls) <= 4:
            chosen, chosen_lines = f, ls
            if trial >= 40 or len(ls) <= 3:
                break
    if chosen is None:
        chosen = best_serif(28)
        chosen_lines = _wrap(draw, label, chosen, max_w)

    title_y = int(SIZE * 0.55)
    _draw_centered(draw, chosen_lines, chosen, title_y, INK, line_gap=10)

    # footer mark -- ink, tiny, tracked
    mark_font = best_sans(11)
    mark = _track("OBEL   //   Vol. I", 4)
    mbb = draw.textbbox((0, 0), mark, font=mark_font)
    mx = (SIZE - (mbb[2] - mbb[0])) // 2 - mbb[0]
    draw.text((mx, SIZE - 60), mark, font=mark_font, fill=SOFT_INK)

    img.convert("RGB").save(OUT_DIR / f"{slug}.png", "PNG", optimize=True)
    print(f"  ok  {slug}.png")


# ------------------------------------------------------------------ manifest
POSTS = [
    ("wonders-post-behind-the-scenes-bottling-mondays", "Behind the Scenes: Bottling Mondays", "STUDIO 003"),
    ("wonders-post-caring-for-your-portable-hole", "Caring for Your Portable Hole", "FIELD GUIDE"),
    ("wonders-post-carl-on-the-moon", "Carl on the Moon", "DISPATCH"),
    ("wonders-post-chaos-seasoning-recipe-roundup", "Chaos Seasoning Roundup", "PANTRY"),
    ("wonders-post-fog-season", "Fog Season", "ALMANAC"),
    ("wonders-post-forbidden-honey-what-does-forbidden-mean", "What Does Forbidden Mean?", "ESSAY"),
    ("wonders-post-hidden-gems-5-overlooked-products", "Five Overlooked Wares", "EDITORS"),
    ("wonders-post-how-to-apply-existential-dread-repellent", "Applying Dread Repellent", "FIELD GUIDE"),
    ("wonders-post-imaginary-ownership-beginners", "Imaginary Ownership: A Primer", "PRIMER"),
    ("wonders-post-interview-with-carl", "Interview with Carl", "INTERVIEW"),
    ("wonders-post-invisible-umbrella-spotlight", "Invisible Umbrella", "SPOTLIGHT"),
    ("wonders-post-memoirs-of-a-left-sock", "Memoirs of a Left Sock", "MEMOIR"),
    ("wonders-post-mildly-haunted-candle-faq", "Mildly Haunted Candle FAQ", "FAQ"),
    ("wonders-post-philosophy-of-bottled-monday-morning", "On Bottling a Monday Morning", "ESSAY"),
    ("wonders-post-pocket-thunder-safety", "Pocket Thunder Safety", "SAFETY"),
    ("wonders-post-spare-tuesday-field-guide", "Spare Tuesday Field Guide", "FIELD GUIDE"),
    ("wonders-post-tangible-wifi-30-day-review", "Tangible WiFi: 30-Day Review", "REVIEW"),
    ("wonders-post-the-art-of-artisanal-silence", "The Art of Artisanal Silence", "ESSAY"),
    ("wonders-post-welcome-to-wonders-and-oddities", "Welcome to Wonders & Oddities", "FIRST DISPATCH"),
    ("wonders-post-year-one-abridged", "Year One, Abridged", "ANNUAL REVIEW"),
]

PAGES = [
    ("wonders-page-about", "About the Shop", "INTRODUCTION"),
    ("wonders-page-contact", "Find the Shop", "CONTACT"),
    ("wonders-page-faq", "Frequently Asked", "POLICIES"),
    ("wonders-page-home", "Welcome", "HOME"),
    ("wonders-page-journal", "From the Workbench", "JOURNAL"),
    ("wonders-page-lookbook", "The Lookbook", "EDITORIAL"),
    ("wonders-page-privacy-policy", "Privacy Policy", "POLICY"),
    ("wonders-page-shipping-returns", "Shipping & Returns", "POLICIES"),
]


def main():
    items = POSTS + PAGES
    print(f"Generating {len(items)} Obel hero cards into {OUT_DIR}/")
    for slug, label, kicker in items:
        make_image(slug, label, kicker)
    print(f"\nDone. {len(items)} hero cards written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
