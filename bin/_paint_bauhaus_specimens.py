#!/usr/bin/env python3
"""Paint Bauhaus geometric specimen JPGs for each Bauhaus product SKU.

Pillow-based, deterministic, offline. Each composition is seeded from
the SKU so re-runs are stable and every image is byte-unique within
the theme. The visual language is the Dessau-era primary palette
(red / yellow / blue / black) on a cream paper, exactly the language
the Bauhaus mockup ships.

Usage:
    python3 bin/_paint_bauhaus_specimens.py
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

THEME_ROOT = Path(__file__).resolve().parent.parent / "bauhaus"
IMAGES_DIR = THEME_ROOT / "playground" / "images"
SKU_MAP_PATH = THEME_ROOT / "playground" / "content" / "product-images.json"
SIZE = 1024
PAPER = (243, 233, 204)
INK = (17, 17, 17)
RED = (213, 38, 39)
YELLOW = (243, 197, 31)
BLUE = (31, 81, 145)
SHAPES = ("circle", "square", "triangle", "bar")
COLOURS = (RED, YELLOW, BLUE)


def seed_for(sku: str) -> random.Random:
    h = hashlib.sha256(sku.encode("utf-8")).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def grain_layer(rng: random.Random) -> Image.Image:
    grain = Image.new("L", (SIZE, SIZE), 0)
    px = grain.load()
    for _ in range(SIZE * SIZE // 24):
        x = rng.randrange(SIZE)
        y = rng.randrange(SIZE)
        px[x, y] = rng.randint(0, 12)
    grain = grain.filter(ImageFilter.GaussianBlur(0.6))
    return grain


def draw_circle(draw: ImageDraw.ImageDraw, box, fill, outline, w):
    draw.ellipse(box, fill=fill, outline=outline, width=w)


def draw_square(draw: ImageDraw.ImageDraw, box, fill, outline, w):
    draw.rectangle(box, fill=fill, outline=outline, width=w)


def draw_triangle(draw: ImageDraw.ImageDraw, box, fill, outline, w):
    x0, y0, x1, y1 = box
    points = [((x0 + x1) // 2, y0), (x1, y1), (x0, y1)]
    draw.polygon(points, fill=fill, outline=outline)
    draw.line([points[0], points[1], points[2], points[0]], fill=outline, width=w, joint="curve")


def draw_bar(draw: ImageDraw.ImageDraw, box, fill, outline, w):
    draw.rectangle(box, fill=fill, outline=outline, width=w)


SHAPE_FNS = {
    "circle": draw_circle,
    "square": draw_square,
    "triangle": draw_triangle,
    "bar": draw_bar,
}


def random_box(rng: random.Random, *, min_size: int, max_size: int, bar: bool = False):
    if bar:
        h = rng.randint(40, 80)
        w = rng.randint(int(SIZE * 0.55), int(SIZE * 0.85))
    else:
        s = rng.randint(min_size, max_size)
        w = h = s
    pad = 80
    x0 = rng.randint(pad, SIZE - pad - w)
    y0 = rng.randint(pad, SIZE - pad - h)
    return (x0, y0, x0 + w, y0 + h)


def paint_specimen(sku: str) -> Image.Image:
    rng = seed_for(sku)
    img = Image.new("RGB", (SIZE, SIZE), PAPER)
    grain = grain_layer(rng)
    paper_grain = Image.merge("RGB", [grain, grain, grain])
    img = Image.eval(Image.composite(paper_grain, img, grain), lambda v: max(0, min(255, v)))
    img.paste(Image.new("RGB", (SIZE, SIZE), PAPER), (0, 0), Image.eval(grain, lambda v: 255 - v))

    draw = ImageDraw.Draw(img)
    line_w = rng.choice((10, 12, 14))
    n_shapes = rng.randint(2, 4)
    used = []
    motif = rng.sample(list(SHAPES), n_shapes)
    palette = list(COLOURS)
    rng.shuffle(palette)
    for i, shape in enumerate(motif):
        colour = palette[i % len(palette)]
        if shape == "bar":
            box = random_box(rng, min_size=160, max_size=420, bar=True)
        else:
            box = random_box(rng, min_size=240, max_size=520)
        SHAPE_FNS[shape](draw, box, colour, INK, line_w)
        used.append((shape, box))

    border = 32
    draw.rectangle((border, border, SIZE - border, SIZE - border), outline=INK, width=line_w)

    tag_h = 40
    tag_w = rng.randint(140, 220)
    tag_x = rng.randint(border + 40, SIZE - border - tag_w - 40)
    tag_y = SIZE - border - tag_h - 40
    draw.rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), fill=PAPER, outline=INK, width=4)

    return img


def main() -> int:
    sku_map = json.loads(SKU_MAP_PATH.read_text(encoding="utf-8"))
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for sku, filename in sorted(sku_map.items()):
        out = IMAGES_DIR / filename
        img = paint_specimen(sku)
        img.save(out, format="JPEG", quality=86, optimize=True, progressive=True)
        written += 1
    print(f"painted {written} bauhaus specimens into {IMAGES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
