#!/usr/bin/env python3
"""
Generate Chonk-style 800×800 images for every Wonders & Oddities product,
post, and page. Output lands in the same directory as this script (images/).

Style: cream bg, pure-black 4px inset border, hard 8px offset drop shadow,
bold geometric shape in one of Chonk's three accent colours, uppercase label.
"""

import math, os, textwrap
from PIL import Image, ImageDraw, ImageFont

# ── Chonk palette ────────────────────────────────────────────────────────────
BASE    = "#F5F1E8"
BLACK   = "#000000"
YELLOW  = "#FFE600"
PINK    = "#FF3C8A"
COBALT  = "#1F4FE0"
WHITE   = "#FFFFFF"

ACCENTS = [YELLOW, PINK, COBALT]

OUT_DIR = os.path.join(os.path.dirname(__file__), "images")
os.makedirs(OUT_DIR, exist_ok=True)

SIZE        = 800
BORDER      = 4
SHADOW_OFF  = 10   # hard offset shadow (pixels, right + down)
INSET       = 32   # inner padding from edge

def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

# ── Shape drawers ─────────────────────────────────────────────────────────────
# Each function draws onto `draw` in the given bounding box with `colour`.

def shape_circle(draw, box, colour):
    draw.ellipse(box, fill=colour, outline=BLACK, width=3)

def shape_square(draw, box, colour):
    draw.rectangle(box, fill=colour, outline=BLACK, width=3)

def shape_diamond(draw, box, colour):
    x0, y0, x1, y1 = box
    cx, cy = (x0+x1)//2, (y0+y1)//2
    pts = [(cx, y0), (x1, cy), (cx, y1), (x0, cy)]
    draw.polygon(pts, fill=colour, outline=BLACK)
    draw.line(pts + [pts[0]], fill=BLACK, width=3)

def shape_triangle(draw, box, colour):
    x0, y0, x1, y1 = box
    cx = (x0+x1)//2
    pts = [(cx, y0), (x1, y1), (x0, y1)]
    draw.polygon(pts, fill=colour, outline=BLACK)
    draw.line(pts + [pts[0]], fill=BLACK, width=3)

def shape_hexagon(draw, box, colour):
    x0, y0, x1, y1 = box
    cx, cy = (x0+x1)/2, (y0+y1)/2
    rx, ry = (x1-x0)/2, (y1-y0)/2
    pts = [
        (cx + rx*math.cos(math.radians(a)),
         cy + ry*math.sin(math.radians(a)))
        for a in range(30, 390, 60)
    ]
    draw.polygon(pts, fill=colour, outline=BLACK)
    draw.line(pts + [pts[0]], fill=BLACK, width=3)

def shape_cross(draw, box, colour):
    x0, y0, x1, y1 = box
    w = (x1-x0)//3
    h = (y1-y0)//3
    cx, cy = (x0+x1)//2, (y0+y1)//2
    draw.rectangle([x0+w, y0, x1-w, y1], fill=colour, outline=BLACK, width=3)
    draw.rectangle([x0, y0+h, x1, y1-h], fill=colour, outline=BLACK, width=3)
    # redraw inner corner fills
    draw.rectangle([x0+w, y0+h, x1-w, y1-h], fill=colour)

def shape_star(draw, box, colour):
    x0, y0, x1, y1 = box
    cx, cy = (x0+x1)/2, (y0+y1)/2
    ro = (x1-x0)/2
    ri = ro * 0.42
    pts = []
    for i in range(10):
        r = ro if i % 2 == 0 else ri
        angle = math.radians(-90 + i * 36)
        pts.append((cx + r*math.cos(angle), cy + r*math.sin(angle)))
    draw.polygon(pts, fill=colour, outline=BLACK)
    draw.line(pts + [pts[0]], fill=BLACK, width=2)

def shape_wave(draw, box, colour):
    """Three horizontal thick lines = simplified 'wave'."""
    x0, y0, x1, y1 = box
    h = (y1 - y0) // 5
    for i, yy in enumerate([y0+h, y0+2*h+4, y0+3*h+8]):
        draw.rectangle([x0, yy, x1, yy+h], fill=colour, outline=BLACK, width=2)

def shape_pill(draw, box, colour):
    draw.rounded_rectangle(box, radius=(box[3]-box[1])//2, fill=colour, outline=BLACK, width=3)

def shape_bolt(draw, box, colour):
    """Lightning bolt polygon."""
    x0, y0, x1, y1 = box
    cx = (x0+x1)//2
    mid_y = (y0+y1)//2
    pts = [
        (cx+20, y0),
        (x0+20, mid_y),
        (cx, mid_y),
        (cx-20, y1),
        (x1-20, mid_y),
        (cx+10, mid_y),
    ]
    draw.polygon(pts, fill=colour, outline=BLACK)
    draw.line(pts + [pts[0]], fill=BLACK, width=3)

SHAPES = [
    shape_circle, shape_square, shape_diamond, shape_triangle,
    shape_hexagon, shape_cross, shape_star, shape_wave,
    shape_pill, shape_bolt,
]

# ── Text helpers ──────────────────────────────────────────────────────────────
def best_font(size):
    """Return a PIL font at the requested size, falling back gracefully."""
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SFCompact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def draw_label(draw, text, y_center, font, max_width, line_gap=8):
    """Draw `text` centred horizontally around `y_center`, wrapping at max_width."""
    words = text.upper().split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        bb = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    # Measure total block height
    total_h = sum(
        draw.textbbox((0, 0), ln, font=font)[3] - draw.textbbox((0, 0), ln, font=font)[1]
        for ln in lines
    ) + line_gap * (len(lines) - 1)

    y = y_center - total_h // 2
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=font)
        w = bb[2] - bb[0]
        h = bb[3] - bb[1]
        x = (SIZE - w) // 2
        # hard shadow
        draw.text((x + 3, y + 3), ln, font=font, fill=BLACK)
        draw.text((x, y), ln, font=font, fill=BLACK)
        y += h + line_gap

# ── Image builder ─────────────────────────────────────────────────────────────
def make_image(slug, label, accent_idx, shape_idx):
    img    = Image.new("RGB", (SIZE, SIZE), hex_to_rgb(BASE))
    draw   = ImageDraw.Draw(img)
    colour = ACCENTS[accent_idx % len(ACCENTS)]
    shape  = SHAPES[shape_idx % len(SHAPES)]

    # ── Shadow rectangle (hard, no blur) ─────────────────────────────────────
    shadow_rect = [
        INSET + SHADOW_OFF,
        INSET + SHADOW_OFF,
        SIZE - INSET + SHADOW_OFF,
        SIZE - INSET + SHADOW_OFF,
    ]
    draw.rectangle(shadow_rect, fill=BLACK)

    # ── Main content card ─────────────────────────────────────────────────────
    card = [INSET, INSET, SIZE - INSET, SIZE - INSET]
    draw.rectangle(card, fill=hex_to_rgb(BASE))

    # ── Shape zone (upper 60 % of card) ──────────────────────────────────────
    card_w = card[2] - card[0]
    card_h = card[3] - card[1]
    shape_margin = 48
    shape_box = [
        card[0] + shape_margin,
        card[1] + shape_margin,
        card[2] - shape_margin,
        card[1] + int(card_h * 0.60),
    ]
    shape(draw, shape_box, colour)

    # ── Divider line ──────────────────────────────────────────────────────────
    divider_y = card[1] + int(card_h * 0.64)
    draw.rectangle([card[0], divider_y, card[2], divider_y + 3], fill=BLACK)

    # ── Label (lower 36 % of card) ────────────────────────────────────────────
    label_zone_top    = divider_y + 3
    label_zone_bottom = card[3]
    label_center_y    = (label_zone_top + label_zone_bottom) // 2

    font_size = 52
    font      = best_font(font_size)
    max_text_w = card_w - shape_margin * 2

    # Shrink font if text too wide
    for size in [52, 44, 36, 28, 22]:
        font = best_font(size)
        test = label.upper()
        bb   = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_text_w or size == 22:
            break

    draw_label(draw, label, label_center_y, font, max_text_w)

    # ── Border ────────────────────────────────────────────────────────────────
    draw.rectangle(card, outline=BLACK, width=BORDER)

    path = os.path.join(OUT_DIR, f"{slug}.png")
    img.save(path, "PNG", optimize=True)
    print(f"  ✓  {slug}.png")

# ── Image manifest ────────────────────────────────────────────────────────────
# (slug, human label, accent_idx 0=yellow 1=pink 2=cobalt, shape_idx 0-9)
PRODUCTS = [
    ("wonders-borrowed-nostalgia",  "Borrowed Nostalgia",              0, 0),
    ("wonders-bottled-morning",     "Bottled Monday Morning",          1, 8),
    ("wonders-chaos-seasoning",     "Chaos Seasoning",                 2, 2),
    ("wonders-cosmic-mystery-box",  "Cosmic Mystery Box",              0, 1),
    ("wonders-deja-vu-session",     "Déjà Vu Session",                 1, 6),
    ("wonders-discount-gravity",    "Discount Gravity",                2, 3),
    ("wonders-dread-repellent",     "Existential Dread Repellent",     0, 9),
    ("wonders-fog-in-bottle",       "Fog in a Bottle",                 1, 0),
    ("wonders-forbidden-honey",     "Forbidden Honey",                 2, 4),
    ("wonders-gently-used-luck",    "Gently Used Luck",                0, 6),
    ("wonders-handcrafted-echo",    "Handcrafted Echo",                1, 7),
    ("wonders-haunted-candle",      "Mildly Haunted Candle",           2, 0),
    ("wonders-imaginary-deed",      "Imaginary Deed",                  0, 1),
    ("wonders-invisible-umbrella",  "Invisible Umbrella",              1, 2),
    ("wonders-left-sock",           "Left Sock",                       2, 3),
    ("wonders-lost-recipe-time",    "Lost Recipe",                     0, 5),
    ("wonders-memory-foam-memory",  "Memory Foam Memory",              1, 8),
    ("wonders-monday-kit",          "Monday Morning Starter Kit",      2, 1),
    ("wonders-moon-dust",           "Moon Dust",                       0, 4),
    ("wonders-one-hand-clapping",   "One Hand Clapping",               1, 3),
    ("wonders-pocket-thunder",      "Pocket Thunder",                  2, 9),
    ("wonders-portable-hole",       "Portable Hole",                   0, 5),
    ("wonders-sensory-starter",     "Sensory Starter Pack",            1, 1),
    ("wonders-silence-jar",         "Silence Jar",                     2, 0),
    ("wonders-spare-key-nowhere",   "Spare Key to Nowhere",            0, 2),
    ("wonders-spare-tuesday",       "Spare Tuesday",                   1, 6),
    ("wonders-tangible-wifi",       "Tangible WiFi",                   2, 7),
    ("wonders-void-sampler",        "Void Sampler",                    0, 3),
    ("wonders-whispering-stone",    "Whispering Stone",                1, 4),
    ("wonders-interdim-bazaar",     "Interdimensional Bazaar",         2, 6),
    ("imaginary-seal",              "Official Imaginary Seal",         0, 4),
]

POSTS = [
    ("wonders-post-behind-the-scenes-bottling-mondays",          "Behind the Scenes: Bottling Mondays",       0, 1),
    ("wonders-post-caring-for-your-portable-hole",               "Caring for Your Portable Hole",             1, 5),
    ("wonders-post-carl-on-the-moon",                            "Carl on the Moon",                          2, 4),
    ("wonders-post-chaos-seasoning-recipe-roundup",              "Chaos Seasoning Recipe Roundup",            0, 2),
    ("wonders-post-fog-season",                                  "Fog Season",                                1, 7),
    ("wonders-post-forbidden-honey-what-does-forbidden-mean",    "What Does Forbidden Mean?",                 2, 0),
    ("wonders-post-hidden-gems-5-overlooked-products",           "Hidden Gems: 5 Overlooked Products",        0, 6),
    ("wonders-post-how-to-apply-existential-dread-repellent",    "How to Apply Dread Repellent",              1, 9),
    ("wonders-post-imaginary-ownership-beginners",               "Imaginary Ownership for Beginners",         2, 3),
    ("wonders-post-interview-with-carl",                         "Interview with Carl",                       0, 4),
    ("wonders-post-invisible-umbrella-spotlight",                "Invisible Umbrella Spotlight",              1, 2),
    ("wonders-post-memoirs-of-a-left-sock",                      "Memoirs of a Left Sock",                    2, 8),
    ("wonders-post-mildly-haunted-candle-faq",                   "Mildly Haunted Candle FAQ",                 0, 0),
    ("wonders-post-philosophy-of-bottled-monday-morning",        "Philosophy of Bottled Monday Morning",      1, 1),
    ("wonders-post-pocket-thunder-safety",                       "Pocket Thunder Safety",                     2, 9),
    ("wonders-post-spare-tuesday-field-guide",                   "Spare Tuesday Field Guide",                 0, 3),
    ("wonders-post-tangible-wifi-30-day-review",                 "Tangible WiFi: 30-Day Review",              1, 7),
    ("wonders-post-the-art-of-artisanal-silence",                "The Art of Artisanal Silence",              2, 5),
    ("wonders-post-welcome-to-wonders-and-oddities",             "Welcome to Wonders & Oddities",             0, 6),
    ("wonders-post-year-one-abridged",                           "Year One, Abridged",                        1, 4),
]

PAGES = [
    ("wonders-page-about",             "About",                  0, 1),
    ("wonders-page-contact",           "Contact",                1, 5),
    ("wonders-page-faq",               "FAQ",                    2, 2),
    ("wonders-page-home",              "Home",                   0, 6),
    ("wonders-page-journal",           "Journal",                1, 0),
    ("wonders-page-lookbook",          "Lookbook",               2, 4),
    ("wonders-page-privacy-policy",    "Privacy Policy",         0, 3),
    ("wonders-page-shipping-returns",  "Shipping & Returns",     1, 8),
]

if __name__ == "__main__":
    all_items = PRODUCTS + POSTS + PAGES
    print(f"Generating {len(all_items)} images into {OUT_DIR}/")
    for i, item in enumerate(all_items):
        slug, label, accent, shape = item
        make_image(slug, label, accent, shape)
    print(f"\nDone. {len(all_items)} images written.")
