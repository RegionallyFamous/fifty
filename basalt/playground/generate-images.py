#!/usr/bin/env python3
"""Generate Foundry-style apothecary cards for every demo product,
journal post, and static page in the Playground blueprint.

Foundry brief (from tmp/foundry.json + foundry/design-intent.md):

  Palette       base #F5EED8   (cream parchment)
                surface #FDF8E8 (lighter cream)
                border #C9B583  (aged brass rule)
                accent #8B2F1F  (oxblood)
                contrast #1C1711 (ink black)
                tertiary #6D5B3A (faded sepia)
  Type          Cormorant Garamond display + italic, IBM Plex Mono detail
  Feel          Victorian apothecary shop card — engraved rule, fleuron
                motif, Roman-numeral date stamp, amber-glass bottle
                silhouette for products. Every card reads as if it was
                printed on rag paper and pasted to the shop window.

Output shapes:

  * product-wo-<slug>.jpg (800x800) — a framed label card with an
    abstracted amber-glass bottle silhouette on the left, a stacked
    oxblood-on-cream label with the product name / catalogue number /
    price motif on the right, and fleuron corner motifs.

  * wonders-page-*.png / wonders-post-*.png (800x800) — a boxed shop
    card with an ornamental frame, a kicker (section label / roman
    numeral volume line), an italic serif title centered inside a
    double hairline rule, and a house mark at the bottom. Intended to
    stand in as hero imagery for the demo journal + pages.

All cards are procedural (no external assets): Pillow draws them from
typographic primitives and 2-3 pre-hashed motifs. Outputs are byte-
stable per-slug so re-running never needlessly dirties the tree.

Run:

    python3 foundry/playground/generate-images.py

Idempotent; overwrites previous outputs. Takes <10s for the 58 cards.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ palette
BASE = (245, 238, 216)        # #F5EED8 cream parchment
SURFACE = (253, 248, 232)     # #FDF8E8 lighter cream
BORDER = (201, 181, 131)      # #C9B583 brass rule
AMBER = (139, 90, 45)         # aged amber glass
AMBER_DARK = (91, 56, 22)
OXBLOOD = (139, 47, 31)       # #8B2F1F accent
INK = (28, 23, 17)            # #1C1711 contrast
SEPIA = (109, 91, 58)         # #6D5B3A tertiary
SHADOW = (168, 148, 102)

OUT_DIR = Path(__file__).parent / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 800
MARGIN = 56

# ------------------------------------------------------------------ fonts
# Foundry's display stack: Cormorant Garamond. Pillow can't load .woff2,
# so fall back to macOS-bundled ornate serifs that sit in-family
# (Didot / Bodoni / Big Caslon / Georgia Italic). On Linux, Liberation
# Serif / DejaVu Serif are the last resort.
SERIF_CANDIDATES = [
    # path, ttc-index, italic?
    ("/System/Library/Fonts/Supplemental/Bodoni 72.ttc", 2, False),   # Bold
    ("/System/Library/Fonts/Supplemental/Bodoni 72.ttc", 1, True),    # Italic
    ("/System/Library/Fonts/Supplemental/Didot.ttc", 0, False),
    ("/System/Library/Fonts/Supplemental/Didot.ttc", 1, True),
    ("/System/Library/Fonts/Supplemental/Big Caslon.ttf", 0, False),
    ("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 1, True),
    ("/System/Library/Fonts/Palatino.ttc", 2, True),
    ("/System/Library/Fonts/Supplemental/Georgia Italic.ttf", 0, True),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0, False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 0, False),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf", 0, True),
]

SANS_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def _load_font(path: str, size: int, index: int = 0):
    try:
        if path.endswith(".ttc"):
            return ImageFont.truetype(path, size, index=index)
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return None


def best_serif(size: int, prefer_italic: bool = False):
    """Return a serif Pillow font; prefer italic when the caller wants display feel."""
    candidates = SERIF_CANDIDATES
    if prefer_italic:
        candidates = sorted(candidates, key=lambda c: not c[2])
    for path, idx, _italic in candidates:
        if not os.path.exists(path):
            continue
        f = _load_font(path, size, idx)
        if f is not None:
            return f
    return ImageFont.load_default()


def best_mono(size: int):
    for path in SANS_CANDIDATES:
        if not os.path.exists(path):
            continue
        f = _load_font(path, size)
        if f is not None:
            return f
    return ImageFont.load_default()


# ------------------------------------------------------------------ painting helpers
def _paper_background(size: int, seed: int) -> Image.Image:
    """Paint a warm cream parchment with subtle tonal variation and grain."""
    img = Image.new("RGB", (size, size), BASE)
    px = img.load()
    rng = random.Random(seed)
    # gentle diagonal wash: lighter in the top-left, darker toward bottom-right
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            r = int(BASE[0] + (SURFACE[0] - BASE[0]) * (1 - t) + rng.randint(-3, 3))
            g = int(BASE[1] + (SURFACE[1] - BASE[1]) * (1 - t) + rng.randint(-3, 3))
            b = int(BASE[2] + (SURFACE[2] - BASE[2]) * (1 - t) + rng.randint(-3, 3))
            px[x, y] = (
                max(0, min(255, r)),
                max(0, min(255, g)),
                max(0, min(255, b)),
            )
    # foxing spots — tiny sepia smudges in a handful of random places
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(rng.randint(6, 14)):
        cx = rng.randint(30, size - 30)
        cy = rng.randint(30, size - 30)
        r = rng.randint(3, 9)
        alpha = rng.randint(8, 24)
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(*SEPIA, alpha),
        )
    return img


def _double_frame(draw: ImageDraw.ImageDraw, inset: int, gap: int = 6) -> None:
    """Thin outer rule + slightly heavier inner rule — classic engraved border."""
    # outer hairline
    draw.rectangle(
        [inset, inset, SIZE - inset - 1, SIZE - inset - 1],
        outline=BORDER,
        width=1,
    )
    # inner rule
    draw.rectangle(
        [inset + gap, inset + gap, SIZE - inset - gap - 1, SIZE - inset - gap - 1],
        outline=BORDER,
        width=2,
    )


def _corner_fleurons(draw: ImageDraw.ImageDraw, inset: int) -> None:
    """Draw a small diamond-motif in each inner corner of the frame."""
    for cx, cy in (
        (inset + 22, inset + 22),
        (SIZE - inset - 22, inset + 22),
        (inset + 22, SIZE - inset - 22),
        (SIZE - inset - 22, SIZE - inset - 22),
    ):
        _draw_fleuron(draw, cx, cy, size=7, fill=OXBLOOD)


def _draw_fleuron(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, fill) -> None:
    """Simple stylised 4-petal fleuron (❦-ish)."""
    r = size
    # horizontal bar + vertical bar + diamond dot
    draw.line([(cx - r * 2, cy), (cx + r * 2, cy)], fill=fill, width=1)
    draw.polygon(
        [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
        outline=fill,
        width=1,
    )
    draw.ellipse([cx - 1, cy - 1, cx + 1, cy + 1], fill=fill)


def _track(s: str, spacer_width: int = 3) -> str:
    """Cheap visual letter-spacing — pad each character with hair-spaces."""
    spacer = " " * (spacer_width // 3 + 1)
    return spacer.join(s)


def _wrap_text(draw, text, font, max_w):
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


def _draw_centered_lines(draw, lines, font, y_center, fill, line_gap=8, x_center=None):
    if x_center is None:
        x_center = SIZE // 2
    metrics = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    heights = [bb[3] - bb[1] for bb in metrics]
    widths = [bb[2] - bb[0] for bb in metrics]
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = y_center - total_h // 2
    for ln, w_, h_, bb in zip(lines, widths, heights, metrics):
        x = x_center - w_ // 2 - bb[0]
        draw.text((x, y - bb[1]), ln, font=font, fill=fill)
        y += h_ + line_gap


# ------------------------------------------------------------------ bottle silhouette
def _draw_bottle(draw: ImageDraw.ImageDraw, cx: int, cy: int, style: str) -> None:
    """Paint a stylised amber-glass apothecary bottle at (cx, cy).

    `style` varies the silhouette across the catalogue so cards don't
    all read as the same vessel. Supported: 'tincture' (tall-slim +
    dropper-cap), 'jar' (squat + flat lid), 'flask' (round-bottom +
    long neck), 'vial' (tiny), 'tin' (round).
    """
    if style == "tincture":
        # tall slim body, narrow neck, dropper cap
        body = [cx - 60, cy - 30, cx + 60, cy + 190]
        neck = [cx - 22, cy - 80, cx + 22, cy - 30]
        cap = [cx - 32, cy - 110, cx + 32, cy - 80]
        draw.rounded_rectangle(body, 14, fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rectangle(neck, fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rounded_rectangle(cap, 4, fill=INK, outline=AMBER_DARK, width=1)
        # label
        draw.rectangle([cx - 44, cy + 20, cx + 44, cy + 130], fill=SURFACE, outline=SEPIA, width=1)
    elif style == "jar":
        body = [cx - 82, cy - 40, cx + 82, cy + 180]
        lid = [cx - 90, cy - 80, cx + 90, cy - 40]
        draw.rounded_rectangle(body, 10, fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rounded_rectangle(lid, 4, fill=INK, outline=AMBER_DARK, width=1)
        draw.rectangle([cx - 60, cy + 10, cx + 60, cy + 140], fill=SURFACE, outline=SEPIA, width=1)
    elif style == "flask":
        # round-bottom with long slim neck
        draw.ellipse([cx - 95, cy, cx + 95, cy + 190], fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rectangle([cx - 18, cy - 80, cx + 18, cy + 10], fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rounded_rectangle([cx - 28, cy - 100, cx + 28, cy - 78], 3, fill=INK, outline=AMBER_DARK, width=1)
        draw.rectangle([cx - 52, cy + 60, cx + 52, cy + 150], fill=SURFACE, outline=SEPIA, width=1)
    elif style == "vial":
        draw.rounded_rectangle([cx - 34, cy - 20, cx + 34, cy + 160], 10, fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rectangle([cx - 16, cy - 50, cx + 16, cy - 20], fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rounded_rectangle([cx - 22, cy - 70, cx + 22, cy - 48], 3, fill=INK, outline=AMBER_DARK, width=1)
        draw.rectangle([cx - 26, cy + 20, cx + 26, cy + 120], fill=SURFACE, outline=SEPIA, width=1)
    else:  # 'tin'
        # round-topped tin (pomade feel)
        draw.ellipse([cx - 90, cy - 100, cx + 90, cy + 40], fill=AMBER, outline=AMBER_DARK, width=2)
        draw.rectangle([cx - 90, cy - 30, cx + 90, cy + 170], fill=AMBER, outline=AMBER_DARK, width=2)
        draw.ellipse([cx - 90, cy + 140, cx + 90, cy + 200], fill=AMBER_DARK)
        draw.ellipse([cx - 72, cy - 40, cx + 72, cy + 30], fill=SURFACE, outline=SEPIA, width=1)


# ------------------------------------------------------------------ cards
def _render_product_card(slug: str, label: str, catalogue_no: str) -> None:
    """Left: amber bottle silhouette. Right: engraved apothecary label."""
    seed = abs(hash(slug)) % (2**31)
    rng = random.Random(seed)
    img = _paper_background(SIZE, seed)
    draw = ImageDraw.Draw(img, "RGBA")

    # ornamental frame
    _double_frame(draw, inset=32)
    _corner_fleurons(draw, inset=32)

    # bottle on the left
    styles = ["tincture", "jar", "flask", "vial", "tin"]
    style = styles[seed % len(styles)]
    _draw_bottle(draw, cx=int(SIZE * 0.33), cy=int(SIZE * 0.44), style=style)

    # label on the right — a cream slab with serif name
    label_left = int(SIZE * 0.56)
    label_right = SIZE - 84
    label_top = int(SIZE * 0.26)
    label_bottom = int(SIZE * 0.78)
    draw.rectangle(
        [label_left, label_top, label_right, label_bottom],
        fill=SURFACE,
        outline=SEPIA,
        width=1,
    )
    # inner label rule
    draw.rectangle(
        [label_left + 8, label_top + 8, label_right - 8, label_bottom - 8],
        outline=OXBLOOD,
        width=1,
    )

    # Catalogue no. (small caps mono)
    cat_font = best_mono(14)
    cat_text = _track(f"NO. {catalogue_no}", 3)
    bb = draw.textbbox((0, 0), cat_text, font=cat_font)
    cx_label = (label_left + label_right) // 2
    draw.text(
        (cx_label - (bb[2] - bb[0]) // 2 - bb[0], label_top + 22),
        cat_text,
        font=cat_font,
        fill=SEPIA,
    )
    # small ornamental rule under the catalogue no.
    rule_y = label_top + 46
    draw.line(
        [(label_left + 30, rule_y), (label_right - 30, rule_y)],
        fill=BORDER,
        width=1,
    )

    # product name — wrapped italic serif
    max_w = label_right - label_left - 40
    chosen_font = None
    chosen_lines: list[str] = []
    chosen_size = 28
    for trial in (44, 38, 32, 28, 24, 20, 18):
        font_try = best_serif(trial, prefer_italic=True)
        lines_try = _wrap_text(draw, label, font_try, max_w)
        if len(lines_try) <= 4:
            chosen_font = font_try
            chosen_lines = lines_try
            chosen_size = trial
            if trial >= 32 or len(lines_try) <= 2:
                break
    if chosen_font is None:
        chosen_font = best_serif(18, prefer_italic=True)
        chosen_lines = _wrap_text(draw, label, chosen_font, max_w)

    _draw_centered_lines(
        draw,
        chosen_lines,
        chosen_font,
        y_center=(label_top + label_bottom) // 2,
        fill=INK,
        line_gap=int(chosen_size * 0.18),
        x_center=cx_label,
    )

    # house mark at the base of the label
    mark_font = best_mono(11)
    mark_text = _track("FOUNDRY \u00b7 APOTHECARY \u00b7 MMXXVI", 2)
    mbb = draw.textbbox((0, 0), mark_text, font=mark_font)
    # scale back if too wide for the label
    if mbb[2] - mbb[0] > label_right - label_left - 30:
        mark_text = _track("FOUNDRY \u00b7 MMXXVI", 2)
        mbb = draw.textbbox((0, 0), mark_text, font=mark_font)
    draw.text(
        (cx_label - (mbb[2] - mbb[0]) // 2 - mbb[0], label_bottom - 22),
        mark_text,
        font=mark_font,
        fill=OXBLOOD,
    )

    # outer fleuron at the bottom of the card, between bottle and label
    fl_y = SIZE - 74
    _draw_fleuron(draw, SIZE // 2, fl_y, size=10, fill=OXBLOOD)

    img = img.convert("RGB")
    out = OUT_DIR / f"product-wo-{slug}.jpg"
    img.save(out, "JPEG", quality=88, optimize=True)
    print(f"  ok  {out.name}")


def _render_hero_card(slug: str, label: str, kicker: str) -> None:
    """Boxed apothecary shop card used as a stand-in for journal posts / pages."""
    seed = abs(hash(slug)) % (2**31) + 991
    img = _paper_background(SIZE, seed)
    draw = ImageDraw.Draw(img, "RGBA")

    _double_frame(draw, inset=32)
    _corner_fleurons(draw, inset=32)

    # kicker
    kicker_font = best_mono(13)
    kicker_text = _track(kicker.upper(), 3)
    kbb = draw.textbbox((0, 0), kicker_text, font=kicker_font)
    draw.text(
        ((SIZE - (kbb[2] - kbb[0])) // 2 - kbb[0], int(SIZE * 0.24)),
        kicker_text,
        font=kicker_font,
        fill=SEPIA,
    )

    # top fleuron + rule
    fy = int(SIZE * 0.32)
    _draw_fleuron(draw, SIZE // 2, fy, size=9, fill=OXBLOOD)
    draw.line(
        [(int(SIZE * 0.22), fy + 20), (int(SIZE * 0.78), fy + 20)],
        fill=BORDER,
        width=1,
    )

    # title
    max_w = SIZE - MARGIN * 2 - 20
    chosen_font = None
    chosen_lines: list[str] = []
    chosen_size = 52
    for trial in (74, 62, 52, 44, 36, 30, 24):
        font_try = best_serif(trial, prefer_italic=True)
        lines_try = _wrap_text(draw, label, font_try, max_w)
        if len(lines_try) <= 5:
            chosen_font = font_try
            chosen_lines = lines_try
            chosen_size = trial
            if trial >= 44 or len(lines_try) <= 3:
                break
    if chosen_font is None:
        chosen_font = best_serif(24, prefer_italic=True)
        chosen_lines = _wrap_text(draw, label, chosen_font, max_w)

    _draw_centered_lines(
        draw,
        chosen_lines,
        chosen_font,
        y_center=int(SIZE * 0.56),
        fill=INK,
        line_gap=int(chosen_size * 0.16),
    )

    # bottom rule + fleuron
    by = int(SIZE * 0.78)
    draw.line(
        [(int(SIZE * 0.22), by), (int(SIZE * 0.78), by)],
        fill=BORDER,
        width=1,
    )
    _draw_fleuron(draw, SIZE // 2, by + 20, size=9, fill=OXBLOOD)

    # house mark
    mark_font = best_mono(11)
    mark_text = _track("THE FOUNDRY APOTHECARY \u00b7 EST. MMXXVI", 2)
    mbb = draw.textbbox((0, 0), mark_text, font=mark_font)
    draw.text(
        ((SIZE - (mbb[2] - mbb[0])) // 2 - mbb[0], SIZE - 68),
        mark_text,
        font=mark_font,
        fill=OXBLOOD,
    )

    img = img.convert("RGB")
    out = OUT_DIR / f"{slug}.png"
    img.save(out, "PNG", optimize=True)
    print(f"  ok  {out.name}")


# ------------------------------------------------------------------ manifest
# Products: slug, display title shown on the label, catalogue number (roman numerals).
PRODUCTS: list[tuple[str, str, str]] = [
    ("borrowed-nostalgia", "Borrowed Nostalgia", "CXII"),
    ("bottled-morning", "Bottled Monday Morning", "I"),
    ("chaos-seasoning", "Chaos Seasoning", "XLVII"),
    ("cosmic-mystery-box", "Cosmic Mystery Box", "LXI"),
    ("deja-vu-session", "Déjà-vu Session", "XXXIII"),
    ("discount-gravity", "Discount Gravity", "VII"),
    ("dread-repellent", "Existential Dread Repellent", "XIX"),
    ("fog-in-bottle", "Fog in a Bottle", "XCII"),
    ("forbidden-honey", "Forbidden Honey", "IV"),
    ("gently-used-luck", "Gently-Used Luck", "LXVIII"),
    ("handcrafted-echo", "Handcrafted Echo", "LV"),
    ("haunted-candle", "Mildly Haunted Candle", "XIII"),
    ("imaginary-deed", "Imaginary Deed", "XXI"),
    ("interdim-bazaar", "Interdimensional Bazaar Token", "LXXX"),
    ("invisible-umbrella", "Invisible Umbrella", "XXXVIII"),
    ("left-sock", "A Single Left Sock", "CI"),
    ("lost-recipe-time", "Lost Recipe for Time", "IX"),
    ("memory-foam-memory", "Memory-Foam Memory", "LXXXIV"),
    ("monday-kit", "Monday-Morning Kit", "II"),
    ("moon-dust", "Certified Lunar Moon Dust", "III"),
    ("one-hand-clapping", "One Hand Clapping", "LXXII"),
    ("pocket-thunder", "Pocket Thunder", "XLI"),
    ("portable-hole", "Portable Hole, 8cm", "XVII"),
    ("sensory-starter", "Sensory Starter Pack", "XXIX"),
    ("silence-jar", "Artisanal Silence, 8oz", "V"),
    ("spare-key-nowhere", "Spare Key to Nowhere", "LIV"),
    ("spare-tuesday", "A Spare Tuesday", "VI"),
    ("tangible-wifi", "Tangible WiFi", "LXXVII"),
    ("void-sampler", "Void Sampler Set", "XCIX"),
    ("whispering-stone", "Whispering Stone", "XXXV"),
]

# Journal posts — kickers are section stamps in the Foundry voice.
POSTS: list[tuple[str, str, str]] = [
    ("wonders-post-behind-the-scenes-bottling-mondays",
     "Behind the Bench: Bottling Mondays", "VOL II \u00b7 NO 03"),
    ("wonders-post-caring-for-your-portable-hole",
     "On the Care of a Portable Hole", "FIELD NOTE"),
    ("wonders-post-carl-on-the-moon",
     "Carl on the Moon, a Dispatch", "DISPATCH"),
    ("wonders-post-chaos-seasoning-recipe-roundup",
     "Chaos Seasoning: a Roundup", "FROM THE PANTRY"),
    ("wonders-post-fog-season",
     "Fog Season, and its Uses", "ALMANAC"),
    ("wonders-post-forbidden-honey-what-does-forbidden-mean",
     "What Exactly is Forbidden About the Honey?", "CORRESPONDENCE"),
    ("wonders-post-hidden-gems-5-overlooked-products",
     "Five Overlooked Remedies from the Upper Shelf", "HOUSE PICKS"),
    ("wonders-post-how-to-apply-existential-dread-repellent",
     "Applying Dread Repellent, Properly", "FIELD NOTE"),
    ("wonders-post-imaginary-ownership-beginners",
     "A Primer on Imaginary Ownership", "PRIMER"),
    ("wonders-post-interview-with-carl",
     "Carl, a Conversation in Two Parts", "INTERVIEW"),
    ("wonders-post-invisible-umbrella-spotlight",
     "The Invisible Umbrella, Spotlit", "PRODUCT NOTE"),
    ("wonders-post-memoirs-of-a-left-sock",
     "Memoirs of a Single Left Sock", "MEMOIR"),
    ("wonders-post-mildly-haunted-candle-faq",
     "The Mildly Haunted Candle FAQ", "ENQUIRIES"),
    ("wonders-post-philosophy-of-bottled-monday-morning",
     "On the Philosophy of Bottled Monday Morning", "ESSAY"),
    ("wonders-post-pocket-thunder-safety",
     "Pocket Thunder, Handled Safely", "SAFETY NOTE"),
    ("wonders-post-spare-tuesday-field-guide",
     "A Field Guide to the Spare Tuesday", "FIELD NOTE"),
    ("wonders-post-tangible-wifi-30-day-review",
     "Tangible WiFi: a Thirty-Day Review", "REVIEW"),
    ("wonders-post-the-art-of-artisanal-silence",
     "The Art of Artisanal Silence", "ESSAY"),
    ("wonders-post-welcome-to-wonders-and-oddities",
     "A Welcome to the Apothecary", "FIRST DISPATCH"),
    ("wonders-post-year-one-abridged",
     "Year One, Abridged in Roman Numerals", "ANNUAL REVIEW"),
]

# Static pages — kickers are site-section stamps.
PAGES: list[tuple[str, str, str]] = [
    ("wonders-page-about", "About the House", "ABOUT"),
    ("wonders-page-contact", "To Correspond with the Apothecary", "CONTACT"),
    ("wonders-page-faq", "Enquiries Most Frequently Put", "ENQUIRIES"),
    ("wonders-page-home", "Carefully Compounded Goods", "WELCOME"),
    ("wonders-page-journal", "The Compounding Journal", "JOURNAL"),
    ("wonders-page-lookbook", "The House Plate, by Lamplight", "PLATES"),
    ("wonders-page-privacy-policy", "Discretion and the Customer's Particulars", "DISCRETION"),
    ("wonders-page-shipping-returns", "Dispatch, Post &amp; Exchanges", "DISPATCH"),
]


def main() -> int:
    print(
        f"Generating {len(PRODUCTS)} product labels + "
        f"{len(POSTS)+len(PAGES)} hero cards into {OUT_DIR}/"
    )
    for slug, label, cat in PRODUCTS:
        _render_product_card(slug, label, cat)
    for slug, label, kicker in POSTS + PAGES:
        _render_hero_card(slug, label, kicker)
    total = len(PRODUCTS) + len(POSTS) + len(PAGES)
    print(f"\nDone. {total} cards written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
