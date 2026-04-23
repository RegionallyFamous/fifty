#!/usr/bin/env python3
"""Generate Lysholm-style 800x800 hero placeholder cards for every
journal post and page.

Lysholm brief (from .cursor/rules/playground-imagery.mdc):

  Nordic home goods, white-on-white. Chalk surfaces, soft tan
  accents, blonde wood, oat tones. Slow, considered, unhurried.
  Hairline rules, deep ink type, generous negative space.

Procedural translation:

  * Chalk-white base (#F7F5F1) with a barely-visible warm-beige
    wash from upper-left so it never reads as flat digital fill.
  * Faint paper-grain noise pass for tactile feel.
  * One blonde-wood swatch detail (a thin warm tan rounded bar
    near the top, intentionally off-center) -- the only chrome.
  * Hairline deep-ink rule under the kicker.
  * Centered title in a thin sans (Inter / Helvetica Neue Light)
    in deep ink #1D1D1D.
  * Tiny "LYSHOLM // EST. 2026" footer mark in fog grey.
  * Off-center wide-tracked kicker (small-cap feel).

Output filenames mirror the obel hero filenames so the seeder picks
them up without any blueprint edits. Idempotent.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ------------------------------------------------------------------ palette
CHALK = (247, 245, 241)      # base #F7F5F1
SURFACE = (252, 250, 246)    # surface #FCFAF6
OAT = (227, 217, 200)        # muted #E3D9C8
BLONDE = (201, 169, 124)     # accent #C9A97C
FOG = (138, 134, 126)        # tertiary #8A867E
INK = (29, 29, 29)           # contrast #1D1D1D

OUT_DIR = Path(__file__).parent / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 800

# ------------------------------------------------------------------ fonts
SANS_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Helvetica Neue.ttc", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
    ("/System/Library/Fonts/SFNS.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]

SANS_LIGHT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Helvetica Neue.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Avenir.ttc", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]


def _load_font(path, size, index=0):
    try:
        if path.endswith(".ttc"):
            return ImageFont.truetype(path, size, index=index)
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return None


def best_sans(size, light=False):
    pool = SANS_LIGHT_CANDIDATES if light else SANS_CANDIDATES
    for path, idx in pool:
        if not os.path.exists(path):
            continue
        f = _load_font(path, size, idx)
        if f is not None:
            return f
    return ImageFont.load_default()


# ------------------------------------------------------------------ painters
def _warm_wash():
    img = Image.new("RGB", (SIZE, SIZE), CHALK)
    px = img.load()
    cx, cy = int(SIZE * 0.18), int(SIZE * 0.20)
    inv_r = 1.0 / (SIZE * 1.0)
    for y in range(SIZE):
        for x in range(SIZE):
            dx, dy = x - cx, y - cy
            t = min(1.0, math.sqrt(dx * dx + dy * dy) * inv_r)
            t = t * t * (3 - 2 * t)
            r = int(SURFACE[0] + (CHALK[0] - SURFACE[0]) * t)
            g = int(SURFACE[1] + (CHALK[1] - SURFACE[1]) * t)
            b = int(SURFACE[2] + (CHALK[2] - SURFACE[2]) * t)
            px[x, y] = (r, g, b)
    return img


def _grain(img, amount=4, seed=0):
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


# ------------------------------------------------------------------ card
def make_image(slug, label, kicker):
    seed = abs(hash(slug)) % (2**31)
    img = _warm_wash()
    img = _grain(img, amount=4, seed=seed)
    draw = ImageDraw.Draw(img, "RGBA")

    # blonde-wood off-center swatch (a soft horizontal bar, intentionally
    # placed slightly off-axis so the composition has air and asymmetry)
    rng = random.Random(seed)
    swatch_y = rng.randint(int(SIZE * 0.18), int(SIZE * 0.26))
    swatch_x = rng.choice([int(SIZE * 0.10), int(SIZE * 0.65)])
    swatch_w = rng.randint(120, 180)
    draw.rounded_rectangle(
        [swatch_x, swatch_y, swatch_x + swatch_w, swatch_y + 6],
        radius=3, fill=BLONDE,
    )

    # kicker (off-center, wide-tracked, fog grey)
    kicker_font = best_sans(13)
    kt = _track(kicker.upper(), 6)
    bb = draw.textbbox((0, 0), kt, font=kicker_font)
    kicker_x = swatch_x
    kicker_y = swatch_y - 26
    draw.text((kicker_x, kicker_y), kt, font=kicker_font, fill=FOG)

    # hairline rule above kicker (the lysholm hairline detail)
    draw.line(
        [(swatch_x, kicker_y - 12), (swatch_x + 32, kicker_y - 12)],
        fill=INK, width=1,
    )

    # centered title -- thin sans, deep ink, generous tracking via line_gap
    max_w = SIZE - 160
    chosen = None
    chosen_lines = []
    for trial in (62, 54, 46, 40, 34, 28, 24):
        f = best_sans(trial, light=True)
        ls = _wrap(draw, label, f, max_w)
        if len(ls) <= 4:
            chosen, chosen_lines = f, ls
            if trial >= 40 or len(ls) <= 3:
                break
    if chosen is None:
        chosen = best_sans(28, light=True)
        chosen_lines = _wrap(draw, label, chosen, max_w)

    title_y = int(SIZE * 0.55)
    _draw_centered(draw, chosen_lines, chosen, title_y, INK, line_gap=10)

    # footer mark
    mark_font = best_sans(11)
    mark = _track("LYSHOLM   //   EST. 2026", 4)
    bb = draw.textbbox((0, 0), mark, font=mark_font)
    mx = (SIZE - (bb[2] - bb[0])) // 2 - bb[0]
    draw.text((mx, SIZE - 60), mark, font=mark_font, fill=FOG)

    img.convert("RGB").save(OUT_DIR / f"{slug}.png", "PNG", optimize=True)
    print(f"  ok  {slug}.png")


# ------------------------------------------------------------------ manifest
POSTS = [
    ("wonders-post-behind-the-scenes-bottling-mondays", "Behind the Bench: Bottling Mondays", "STUDIO  /  003"),
    ("wonders-post-caring-for-your-portable-hole", "On the Care of a Portable Hole", "FIELD NOTE"),
    ("wonders-post-carl-on-the-moon", "Carl on the Moon", "DISPATCH"),
    ("wonders-post-chaos-seasoning-recipe-roundup", "A Roundup of Chaos Seasoning", "PANTRY"),
    ("wonders-post-fog-season", "Fog Season", "ALMANAC"),
    ("wonders-post-forbidden-honey-what-does-forbidden-mean", "What Does Forbidden Mean?", "ESSAY"),
    ("wonders-post-hidden-gems-5-overlooked-products", "Five Quiet Wares", "EDITORS"),
    ("wonders-post-how-to-apply-existential-dread-repellent", "Applying Dread Repellent", "FIELD NOTE"),
    ("wonders-post-imaginary-ownership-beginners", "Imaginary Ownership: A Primer", "PRIMER"),
    ("wonders-post-interview-with-carl", "Interview with Carl", "INTERVIEW"),
    ("wonders-post-invisible-umbrella-spotlight", "On the Invisible Umbrella", "SPOTLIGHT"),
    ("wonders-post-memoirs-of-a-left-sock", "Memoirs of a Left Sock", "MEMOIR"),
    ("wonders-post-mildly-haunted-candle-faq", "Mildly Haunted: A Short FAQ", "FAQ"),
    ("wonders-post-philosophy-of-bottled-monday-morning", "On Bottling a Monday Morning", "ESSAY"),
    ("wonders-post-pocket-thunder-safety", "Pocket Thunder, Considered", "SAFETY"),
    ("wonders-post-spare-tuesday-field-guide", "A Field Guide to Spare Tuesdays", "FIELD GUIDE"),
    ("wonders-post-tangible-wifi-30-day-review", "Thirty Days of Tangible WiFi", "REVIEW"),
    ("wonders-post-the-art-of-artisanal-silence", "The Art of Artisanal Silence", "ESSAY"),
    ("wonders-post-welcome-to-wonders-and-oddities", "Welcome to the Workshop", "FIRST NOTE"),
    ("wonders-post-year-one-abridged", "Year One, Abridged", "ANNUAL"),
]

PAGES = [
    ("wonders-page-about", "About the Workshop", "INTRODUCTION"),
    ("wonders-page-contact", "Find the Workshop", "CONTACT"),
    ("wonders-page-faq", "Frequently Asked", "POLICIES"),
    ("wonders-page-home", "Welcome", "HOME"),
    ("wonders-page-journal", "From the Bench", "JOURNAL"),
    ("wonders-page-lookbook", "The Lookbook", "EDITORIAL"),
    ("wonders-page-privacy-policy", "Privacy", "POLICY"),
    ("wonders-page-shipping-returns", "Shipping & Returns", "POLICIES"),
]


def main():
    items = POSTS + PAGES
    print(f"Generating {len(items)} Lysholm hero cards into {OUT_DIR}/")
    for slug, label, kicker in items:
        make_image(slug, label, kicker)
    print(f"\nDone. {len(items)} hero cards written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
