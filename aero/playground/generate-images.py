#!/usr/bin/env python3
"""Generate Aero-style 800x800 hero placeholder cards for every
journal post and page.

Aero brief (from style.css Description):

  A Y2K iridescent WooCommerce block theme: holographic pastels,
  glassy chrome buttons, sparkle product cards, bubbly wordmark.

Procedural translation:

  * Holographic gradient background (lavender -> pink -> mint)
    with a soft cyan halo on the upper-right corner so it feels
    iridescent rather than flat.
  * Soft white "frosted" plate centered on the card, with a
    subtle drop-glow.
  * Bubbly display title in a heavy rounded sans (Chango-ish);
    plus a small uppercase tracked-out kicker.
  * Sparkle motif (4-point stars) scattered across the bg per-slug
    so 28 cards never look identical.
  * "AERO * SPARKLE OFFLINE" footer mark in deep purple.

Output filenames mirror the obel hero filenames so the seeder picks
them up without any blueprint edits. Idempotent; overwrites
previous outputs.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ------------------------------------------------------------------ palette
LAVENDER = (245, 238, 255)   # base #F5EEFF
PINK = (255, 238, 247)       # subtle #FFEEF7
MINT = (212, 245, 230)       # holographic mint accent
CYAN = (200, 235, 255)       # halo
DEEP = (45, 31, 102)         # contrast #2D1F66
PLUM = (107, 95, 168)        # tertiary #6B5FA8
WHITE = (255, 255, 255)
SPARKLE = (180, 145, 255)

OUT_DIR = Path(__file__).parent / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 800

# ------------------------------------------------------------------ fonts
SERIF_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Chango.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Helvetica.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Bodoni 72.ttc", 0),
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


def best_display(size):
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


# ------------------------------------------------------------------ bg
def _holographic_bg(seed):
    """Linear-ish iridescent wash: lavender -> pink (left-to-right) +
    a mint diagonal stripe + a cyan halo top-right."""
    img = Image.new("RGB", (SIZE, SIZE), LAVENDER)
    px = img.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = x / SIZE
            r = int(LAVENDER[0] + (PINK[0] - LAVENDER[0]) * t)
            g = int(LAVENDER[1] + (PINK[1] - LAVENDER[1]) * t)
            b = int(LAVENDER[2] + (PINK[2] - LAVENDER[2]) * t)
            # diagonal mint stripe
            d = (x + y) / (SIZE * 2)
            stripe = math.exp(-((d - 0.5) ** 2) / 0.04)
            r = int(r + (MINT[0] - r) * stripe * 0.35)
            g = int(g + (MINT[1] - g) * stripe * 0.35)
            b = int(b + (MINT[2] - b) * stripe * 0.35)
            # cyan halo top-right
            dx = (x - SIZE * 0.85) / SIZE
            dy = (y - SIZE * 0.15) / SIZE
            halo = math.exp(-(dx * dx + dy * dy) / 0.05)
            r = int(r + (CYAN[0] - r) * halo * 0.55)
            g = int(g + (CYAN[1] - g) * halo * 0.55)
            b = int(b + (CYAN[2] - b) * halo * 0.55)
            px[x, y] = (r, g, b)
    return img


def _draw_sparkle(draw, cx, cy, r, fill):
    """4-point sparkle (asterisk-like)."""
    draw.line([(cx - r, cy), (cx + r, cy)], fill=fill, width=2)
    draw.line([(cx, cy - r), (cx, cy + r)], fill=fill, width=2)
    s = int(r * 0.7)
    draw.line([(cx - s, cy - s), (cx + s, cy + s)], fill=fill, width=1)
    draw.line([(cx - s, cy + s), (cx + s, cy - s)], fill=fill, width=1)
    draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=fill)


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
    rng = random.Random(seed)

    img = _holographic_bg(seed)
    draw = ImageDraw.Draw(img, "RGBA")

    # sparkle scatter (deterministic per slug)
    for _ in range(12):
        cx = rng.randint(40, SIZE - 40)
        cy = rng.randint(40, SIZE - 40)
        r = rng.randint(6, 14)
        if 200 < cx < 600 and 240 < cy < 560:
            continue  # keep clear of plate
        _draw_sparkle(draw, cx, cy, r, (*SPARKLE, 200))

    # frosted plate (white with soft alpha + a softer drop-glow)
    plate = [120, 220, SIZE - 120, SIZE - 220]
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        [plate[0] - 8, plate[1] - 8, plate[2] + 8, plate[3] + 8],
        radius=24, fill=(*PLUM, 60),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rounded_rectangle(plate, radius=20, fill=(255, 255, 255, 220),
                           outline=(*PLUM, 90), width=1)

    # kicker
    kicker_font = best_sans(15)
    kt = _track(kicker.upper(), 4)
    bb = draw.textbbox((0, 0), kt, font=kicker_font)
    kx = (SIZE - (bb[2] - bb[0])) // 2 - bb[0]
    draw.text((kx, plate[1] + 30), kt, font=kicker_font, fill=PLUM)

    # title -- bubbly display, shrink to fit
    max_w = (plate[2] - plate[0]) - 60
    chosen = None
    chosen_lines = []
    for trial in (60, 52, 44, 38, 32, 28, 24):
        f = best_display(trial)
        ls = _wrap(draw, label, f, max_w)
        if len(ls) <= 4:
            chosen, chosen_lines = f, ls
            if trial >= 38 or len(ls) <= 3:
                break
    if chosen is None:
        chosen = best_display(28)
        chosen_lines = _wrap(draw, label, chosen, max_w)

    title_y = (plate[1] + plate[3]) // 2 + 8
    _draw_centered(draw, chosen_lines, chosen, title_y, DEEP, line_gap=8)

    # footer mark
    mark_font = best_sans(11)
    mark = _track("AERO   *   SPARKLE OFFLINE", 3)
    bb = draw.textbbox((0, 0), mark, font=mark_font)
    mx = (SIZE - (bb[2] - bb[0])) // 2 - bb[0]
    draw.text((mx, SIZE - 50), mark, font=mark_font, fill=(*DEEP, 200))

    img.convert("RGB").save(OUT_DIR / f"{slug}.png", "PNG", optimize=True)
    print(f"  ok  {slug}.png")


# ------------------------------------------------------------------ manifest
POSTS = [
    ("wonders-post-behind-the-scenes-bottling-mondays", "Behind the Scenes: Bottling Mondays", "DROP 003"),
    ("wonders-post-caring-for-your-portable-hole", "Caring for Your Portable Hole", "FIELD GUIDE"),
    ("wonders-post-carl-on-the-moon", "Carl on the Moon", "DISPATCH"),
    ("wonders-post-chaos-seasoning-recipe-roundup", "Chaos Seasoning Roundup", "PANTRY"),
    ("wonders-post-fog-season", "Fog Season", "WEATHER"),
    ("wonders-post-forbidden-honey-what-does-forbidden-mean", "What Does Forbidden Mean?", "ESSAY"),
    ("wonders-post-hidden-gems-5-overlooked-products", "5 Overlooked Wares", "PICKS"),
    ("wonders-post-how-to-apply-existential-dread-repellent", "Applying Dread Repellent", "HOW TO"),
    ("wonders-post-imaginary-ownership-beginners", "Imaginary Ownership 101", "PRIMER"),
    ("wonders-post-interview-with-carl", "Interview with Carl", "INTERVIEW"),
    ("wonders-post-invisible-umbrella-spotlight", "Invisible Umbrella", "SPOTLIGHT"),
    ("wonders-post-memoirs-of-a-left-sock", "Memoirs of a Left Sock", "MEMOIR"),
    ("wonders-post-mildly-haunted-candle-faq", "Mildly Haunted Candle FAQ", "FAQ"),
    ("wonders-post-philosophy-of-bottled-monday-morning", "Philosophy of Mondays", "ESSAY"),
    ("wonders-post-pocket-thunder-safety", "Pocket Thunder Safety", "SAFETY"),
    ("wonders-post-spare-tuesday-field-guide", "Spare Tuesday Field Guide", "FIELD GUIDE"),
    ("wonders-post-tangible-wifi-30-day-review", "Tangible WiFi: 30-Day", "REVIEW"),
    ("wonders-post-the-art-of-artisanal-silence", "The Art of Artisanal Silence", "ESSAY"),
    ("wonders-post-welcome-to-wonders-and-oddities", "Welcome to Wonders & Oddities", "FIRST DROP"),
    ("wonders-post-year-one-abridged", "Year One, Abridged", "ANNUAL"),
]

PAGES = [
    ("wonders-page-about", "About", "INTRO"),
    ("wonders-page-contact", "Contact", "REACH US"),
    ("wonders-page-faq", "FAQ", "POLICIES"),
    ("wonders-page-home", "Welcome", "HOME"),
    ("wonders-page-journal", "Journal", "DISPATCHES"),
    ("wonders-page-lookbook", "Lookbook", "EDITORIAL"),
    ("wonders-page-privacy-policy", "Privacy", "POLICY"),
    ("wonders-page-shipping-returns", "Shipping & Returns", "POLICY"),
]


def main():
    items = POSTS + PAGES
    print(f"Generating {len(items)} Aero hero cards into {OUT_DIR}/")
    for slug, label, kicker in items:
        make_image(slug, label, kicker)
    print(f"\nDone. {len(items)} hero cards written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
