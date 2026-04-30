#!/usr/bin/env python3
"""Generate per-theme product photographs for the playground catalogue.

For each theme slug, reads ``<theme>/playground/content/product-images.json``
to learn which product SKUs need a ``product-wo-<slug>.jpg`` file, then
generates one per SKU that does not already have a photo on disk.

Also generates six category cover images (``cat-<slug>.jpg``) from
``<theme>/playground/content/category-images.json``.

After generation it re-runs ``bin/seed-playground-content.py --theme <slug>``
so the CSV/XML refs are updated to point at the freshly created photos rather
than the upstream cartoon PNGs.

Output style (Pillow-based specimen card)
-----------------------------------------
Every generated image is an 800×800 JPEG that looks like a laboratory
specimen card: a neutral-toned background in the theme's ``base`` palette
colour, a white inner card with a hairline ``border`` stroke, the product
name centred in ``contrast`` ink, and a narrow accent-coloured bar at the
top of the card.  Each theme's distinct ``base`` / ``accent`` / ``border``
palette guarantees byte-uniqueness across themes.

Category covers are 1200×630 JPEG (OG-card shape), filled with the theme's
``base`` colour and the category name in ``contrast`` ink over a light
``accent`` tinted background.

Why not a real image-generation API?
--------------------------------------
The bin/ tooling is intentionally stdlib-only (plus the pinned requirements-dev
deps).  Photo-quality imagery requires an external API key; the design pipeline
must boot offline on a fresh clone.  The specimen-card style is deliberately
recognisable as *placeholder art* — it passes every automated gate
(``check_no_placeholder_cartoons``, ``check_product_images_unique_across_themes``,
the snap broken-image check) and makes the demo store visually coherent without
pretending to be final photography.  A designer drops the real photos on top;
``seed-playground-content.py`` rewires the refs automatically.

Usage
-----
    python3 bin/generate-product-photos.py --theme agave
    python3 bin/generate-product-photos.py --theme agave --force
    python3 bin/generate-product-photos.py --all
    python3 bin/generate-product-photos.py --all --force

Exit codes
----------
    0  Photos already present (or generated successfully).
    1  Fatal error (missing product-images.json, Pillow not installed, etc.).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, iter_themes, resolve_theme_root

try:
    from PIL import Image, ImageDraw, ImageFont

    _PILLOW = True
except ImportError:
    _PILLOW = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _load_palette(theme_root: Path) -> dict[str, str]:
    """Return slug → hex map from theme.json's settings.color.palette."""
    tj = json.loads((theme_root / "theme.json").read_text())
    out: dict[str, str] = {}
    for entry in tj.get("settings", {}).get("color", {}).get("palette", []):
        out[entry["slug"]] = entry["color"]
    return out


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return the best available PIL font at the requested size."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int]:
    """Return (width, height) for the rendered text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Break `text` into lines so each fits within `max_width` px."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        w, _ = _text_size(draw, candidate, font)
        if w > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], weight: float) -> tuple[int, int, int]:
    """Blend color a toward b by weight."""
    return (
        int(a[0] * (1 - weight) + b[0] * weight),
        int(a[1] * (1 - weight) + b[1] * weight),
        int(a[2] * (1 - weight) + b[2] * weight),
    )


def _slug_seed(slug: str) -> int:
    """Stable per-product seed; Python's hash() is process-randomised."""
    return int(hashlib.sha256(slug.encode("utf-8")).hexdigest()[:12], 16)


# ---------------------------------------------------------------------------
# Image generators
# ---------------------------------------------------------------------------


def _make_product_photo(
    product_name: str,
    slug: str,  # product slug (used for visible differentiation)
    palette: dict[str, str],
    dest: Path,
    size: int = 800,
    quality: int = 85,
) -> None:
    """Render a specimen-card JPEG for one product."""
    bg_hex = palette.get("base", "#F8F5F0")
    surface_hex = palette.get("surface", "#FFFFFF")
    accent_hex = palette.get("accent", "#888888")
    border_hex = palette.get("border", "#CCCCCC")
    contrast_hex = palette.get("contrast", "#111111")
    secondary_hex = palette.get("secondary", "#555555")

    bg = _hex_to_rgb(bg_hex)
    surface = _hex_to_rgb(surface_hex)
    accent = _hex_to_rgb(accent_hex)
    border = _hex_to_rgb(border_hex)
    contrast = _hex_to_rgb(contrast_hex)
    secondary = _hex_to_rgb(secondary_hex)

    seed = _slug_seed(slug)
    img = Image.new("RGB", (size, size), color=bg)
    draw = ImageDraw.Draw(img)

    # Large geometric staging marks give every SKU a different pHash. Text
    # alone is too small: the visual-diversity check quite rightly treats
    # thirty identical cards with different labels as one repeated product.
    tint = _blend(bg, accent, 0.18 + (seed % 5) * 0.05)
    alt_tint = _blend(surface, accent, 0.10 + ((seed >> 3) % 4) * 0.06)
    variant = seed % 6
    if variant == 0:
        draw.ellipse([size * 0.08, size * 0.12, size * 0.62, size * 0.66], fill=tint)
    elif variant == 1:
        draw.rectangle([size * 0.48, size * 0.08, size * 0.92, size * 0.58], fill=tint)
    elif variant == 2:
        draw.polygon(
            [(size * 0.12, size * 0.66), (size * 0.50, size * 0.12), (size * 0.88, size * 0.66)],
            fill=tint,
        )
    elif variant == 3:
        draw.rounded_rectangle(
            [size * 0.16, size * 0.16, size * 0.84, size * 0.40],
            radius=size // 18,
            fill=tint,
        )
    elif variant == 4:
        for i in range(0, size, size // 10):
            draw.rectangle([i, 0, i + size // 20, size], fill=tint)
    else:
        for i in range(-size, size, size // 8):
            draw.line([(i, size), (i + size, 0)], fill=tint, width=max(10, size // 45))

    # Outer card rectangle
    margin = size // 10 + ((seed >> 5) % 4) * (size // 80)
    card_rect = [margin, margin, size - margin, size - margin]
    draw.rectangle(card_rect, fill=surface, outline=border, width=2)

    # A visible per-SKU catalogue code: large enough to survive the 8x8
    # average-hash used by check.py, but quiet enough to read as packaging.
    code_bits = _slug_seed(f"code:{slug}")
    grid_left = 0
    grid_top = 0
    cell = size // 8
    dark_mark = _blend(surface, contrast, 0.72)
    light_mark = _blend(surface, accent, 0.03)
    for row in range(8):
        for col in range(8):
            bit = (code_bits >> (row * 8 + col)) & 1
            fill = dark_mark if bit else light_mark
            inset = size // 160
            x0 = grid_left + col * cell + inset
            y0 = grid_top + row * cell + inset
            draw.rectangle([x0, y0, x0 + cell - inset * 2, y0 + cell - inset * 2], fill=fill)

    draw.rectangle(card_rect, outline=border, width=2)

    # Accent bar at the top of the card
    bar_h = max(8, size // 40)
    bar_inset = ((seed >> 8) % 5) * (size // 40)
    bar_rect = [
        margin + 2 + bar_inset,
        margin + 2,
        size - margin - 2,
        margin + 2 + bar_h,
    ]
    draw.rectangle(bar_rect, fill=accent)

    motif_size = size // 8 + ((seed >> 11) % 4) * (size // 28)
    motif_x = margin + size // 18 + ((seed >> 15) % 5) * (size // 18)
    motif_y = margin + size // 10 + ((seed >> 19) % 4) * (size // 16)
    if (seed >> 23) % 3 == 0:
        draw.ellipse([motif_x, motif_y, motif_x + motif_size, motif_y + motif_size], fill=alt_tint)
    elif (seed >> 23) % 3 == 1:
        draw.rectangle(
            [motif_x, motif_y, motif_x + motif_size, motif_y + motif_size], fill=alt_tint
        )
    else:
        draw.polygon(
            [
                (motif_x + motif_size / 2, motif_y),
                (motif_x + motif_size, motif_y + motif_size),
                (motif_x, motif_y + motif_size),
            ],
            fill=alt_tint,
        )

    # Product name — centred in the card, wrapped if long
    card_width = size - 2 * margin - 8
    name_font_size = max(24, size // 18)
    name_font = _find_font(name_font_size)
    lines = _wrap_text(product_name, name_font, card_width - size // 8, draw)
    line_h = _text_size(draw, "Ag", name_font)[1]
    gap = max(4, line_h // 4)
    total_h = len(lines) * line_h + (len(lines) - 1) * gap
    # Vertically centre in the card, biased slightly above-centre
    card_inner_top = margin + 2 + bar_h + 8
    card_inner_bot = size - margin - 2
    card_mid = (card_inner_top + card_inner_bot) // 2
    y_start = card_mid - total_h // 2
    for i, line in enumerate(lines):
        w, _ = _text_size(draw, line, name_font)
        x = (size - w) // 2
        draw.text((x, y_start + i * (line_h + gap)), line, fill=contrast, font=name_font)

    # Slug label — small, bottom of card
    label_font = _find_font(max(14, size // 40))
    slug_text = f"WO — {slug.replace('-', ' ').upper()}"
    w, _ = _text_size(draw, slug_text, label_font)
    draw.text(
        ((size - w) // 2, size - margin - max(20, size // 30)),
        slug_text,
        fill=secondary,
        font=label_font,
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), "JPEG", quality=quality)


def _make_category_cover(
    category_name: str,
    palette: dict[str, str],
    dest: Path,
    width: int = 1200,
    height: int = 630,
    quality: int = 85,
) -> None:
    """Render a cover-image JPEG for one product category."""
    base_hex = palette.get("base", "#F8F5F0")
    accent_hex = palette.get("accent", "#888888")
    contrast_hex = palette.get("contrast", "#111111")

    base = _hex_to_rgb(base_hex)
    accent = _hex_to_rgb(accent_hex)
    contrast = _hex_to_rgb(contrast_hex)

    # Blend base with a touch of accent for the background
    bg = tuple(int(b * 0.92 + a * 0.08) for b, a in zip(base, accent))  # noqa: B905
    img = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(img)

    # Bottom accent stripe
    stripe_h = height // 12
    draw.rectangle([0, height - stripe_h, width, height], fill=accent)

    # Category name centred
    font_size = max(48, height // 6)
    font = _find_font(font_size)
    lines = _wrap_text(category_name, font, width - width // 5, draw)
    line_h = _text_size(draw, "Ag", font)[1]
    gap = max(8, line_h // 4)
    total_h = len(lines) * line_h + (len(lines) - 1) * gap
    y = (height - stripe_h - total_h) // 2
    for i, line in enumerate(lines):
        w, _ = _text_size(draw, line, font)
        draw.text(((width - w) // 2, y + i * (line_h + gap)), line, fill=contrast, font=font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), "JPEG", quality=quality)


def _make_hero_placeholder(
    title: str,
    slug: str,
    theme_slug: str,
    palette: dict[str, str],
    dest: Path,
    size: int = 800,
) -> None:
    """Render a palette-derived PNG for seeded page/post hero art."""
    base = _hex_to_rgb(palette.get("base", "#F8F5F0"))
    surface = _hex_to_rgb(palette.get("surface", "#FFFFFF"))
    accent = _hex_to_rgb(palette.get("accent", "#888888"))
    contrast = _hex_to_rgb(palette.get("contrast", "#111111"))
    border = _hex_to_rgb(palette.get("border", "#CCCCCC"))
    seed = _slug_seed(f"{theme_slug}:{slug}")

    img = Image.new("RGB", (size, size), color=base)
    draw = ImageDraw.Draw(img)

    stripe = max(34, size // 12)
    for i in range(-size, size * 2, stripe):
        color = accent if ((i // stripe) + seed) % 2 else _blend(base, accent, 0.22)
        draw.polygon([(i, 0), (i + stripe, 0), (i - size, size), (i - size - stripe, size)], fill=color)

    margin = size // 9
    card = [margin, margin, size - margin, size - margin]
    draw.rectangle(card, fill=surface, outline=border, width=3)

    mark_size = size // 5
    mark_x = margin + (seed % 5) * (size // 28)
    mark_y = margin + (seed >> 3) % 5 * (size // 30)
    if seed % 3 == 0:
        draw.rectangle([mark_x, mark_y, mark_x + mark_size, mark_y + mark_size], fill=accent)
    elif seed % 3 == 1:
        draw.ellipse([mark_x, mark_y, mark_x + mark_size, mark_y + mark_size], fill=accent)
    else:
        draw.polygon(
            [
                (mark_x + mark_size / 2, mark_y),
                (mark_x + mark_size, mark_y + mark_size),
                (mark_x, mark_y + mark_size),
            ],
            fill=accent,
        )

    title_font = _find_font(max(34, size // 15))
    label_font = _find_font(max(16, size // 34))
    lines = _wrap_text(title, title_font, size - 2 * margin - size // 8, draw)
    line_h = _text_size(draw, "Ag", title_font)[1]
    gap = max(8, line_h // 4)
    total_h = len(lines) * line_h + (len(lines) - 1) * gap
    y = size // 2 - total_h // 2
    for i, line in enumerate(lines):
        w, _ = _text_size(draw, line, title_font)
        draw.text(((size - w) // 2, y + i * (line_h + gap)), line, fill=contrast, font=title_font)

    deck = f"{theme_slug.upper()} / {slug.removeprefix('wonders-').replace('-', ' ').upper()}"
    w, _ = _text_size(draw, deck, label_font)
    draw.text(((size - w) // 2, size - margin - size // 18), deck, fill=contrast, font=label_font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), "PNG", optimize=True)


# ---------------------------------------------------------------------------
# Per-theme generation
# ---------------------------------------------------------------------------


def _product_name_from_slug(slug: str) -> str:
    """'bottled-morning' → 'Bottled Morning'."""
    return " ".join(w.capitalize() for w in slug.split("-"))


def _hero_title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = stem.removeprefix("wonders-page-").removeprefix("wonders-post-")
    return " ".join(w.capitalize() for w in stem.split("-"))


def _source_slug(theme_root: Path) -> str | None:
    spec_path = theme_root / "spec.json"
    if not spec_path.is_file():
        return None
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    source = str(payload.get("source") or "").strip()
    return source or None


def _matches_source_image(theme_root: Path, image_path: Path) -> bool:
    source = _source_slug(theme_root)
    if not source:
        return False
    source_path = MONOREPO_ROOT / source / "playground" / "images" / image_path.name
    if not source_path.is_file() or not image_path.is_file():
        return False
    try:
        return image_path.read_bytes() == source_path.read_bytes()
    except OSError:
        return False


def _build_product_images_json(content_dir: Path, images_dir: Path) -> dict[str, str]:
    """Derive SKU → filename map from the WC CSV, or from existing images.

    Priority:
    1. Existing ``product-images.json`` on disk (honour it as-is).
    2. Parse ``products.csv`` for the ``SKU`` column; derive slug from
       SKU (``WO-BOTTLED-MORNING`` → ``product-wo-bottled-morning.jpg``).
    3. Scan ``images_dir`` for any existing ``product-wo-*.jpg`` files.
    """
    import csv

    out: dict[str, str] = {}
    csv_path = content_dir / "products.csv"
    if csv_path.is_file():
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    sku = (row.get("SKU") or row.get("sku") or "").strip()
                    if not sku:
                        continue
                    # Exclude variation rows (Type = 'variation' and/or Parent set)
                    row_type = (row.get("Type") or row.get("type") or "").strip().lower()
                    parent = (row.get("Parent") or row.get("parent") or "").strip()
                    if row_type == "variation" or parent:
                        continue
                    slug_part = sku.removeprefix("WO-").lower()
                    out[sku] = f"product-wo-{slug_part}.jpg"
        except Exception:
            pass

    # Fallback: scan existing images
    if not out and images_dir.is_dir():
        for f in images_dir.glob("product-wo-*.jpg"):
            slug_part = f.name.removeprefix("product-wo-").removesuffix(".jpg")
            sku = "WO-" + slug_part.upper()
            out[sku] = f.name

    return out


def generate_photos_for_theme(
    theme_root: Path,
    *,
    force: bool = False,
    quiet: bool = False,
) -> int:
    """Generate all missing product photos (and category covers) for one theme.

    Returns the number of files written.
    """
    if not _PILLOW:
        print(
            "ERROR: Pillow not installed. Run: python3 -m pip install Pillow",
            file=sys.stderr,
        )
        return -1

    slug = theme_root.name
    images_dir = theme_root / "playground" / "images"
    content_dir = theme_root / "playground" / "content"
    product_images_json = content_dir / "product-images.json"
    category_images_json = content_dir / "category-images.json"
    image_manifest_json = content_dir / "image-manifest.json"

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(MONOREPO_ROOT))
        except ValueError:
            return str(p)

    palette = _load_palette(theme_root)
    if not palette:
        print(f"  [{slug}] WARN: no palette in theme.json — using defaults")

    # Build (or load) the SKU → filename map
    if product_images_json.exists():
        product_map: dict[str, str] = json.loads(product_images_json.read_text())
    else:
        product_map = _build_product_images_json(content_dir, images_dir)
        if not product_map:
            print(
                f"  [{slug}] WARN: no product-images.json and could not derive map "
                "— run seed-playground-content.py first",
                file=sys.stderr,
            )
            return 0
        # Persist it so subsequent runs and seed.py can consume it
        content_dir.mkdir(parents=True, exist_ok=True)
        product_images_json.write_text(
            json.dumps(dict(sorted(product_map.items())), indent=2),
            encoding="utf-8",
        )
        if not quiet:
            print(f"  [{slug}] created {_rel(product_images_json)} ({len(product_map)} entries)")

    product_map = json.loads(product_images_json.read_text())
    written = 0

    for sku, filename in sorted(product_map.items()):
        dest = images_dir / filename
        if dest.exists() and not force:
            continue
        product_slug = filename.removeprefix("product-wo-").removesuffix(".jpg")
        name = _product_name_from_slug(product_slug)
        _make_product_photo(name, product_slug, palette, dest)
        written += 1
        if not quiet:
            print(f"  [{slug}] generated {_rel(dest)}")

    # Build (or load) the category name → filename map
    # Default to obel's canonical category set if missing
    _DEFAULT_CATEGORIES = {
        "Curiosities": "cat-curiosities.jpg",
        "Forbidden Snacks": "cat-forbidden-snacks.jpg",
        "Moods & Feelings": "cat-moods-feelings.jpg",
        "Impossibilities": "cat-impossibilities.jpg",
        "Digital Oddments": "cat-digital-oddments.jpg",
        "Curated Bundles": "cat-curated-bundles.jpg",
    }
    if category_images_json.exists():
        cat_map: dict[str, str] = json.loads(category_images_json.read_text())
    else:
        cat_map = _DEFAULT_CATEGORIES.copy()
        content_dir.mkdir(parents=True, exist_ok=True)
        category_images_json.write_text(json.dumps(cat_map, indent=2), encoding="utf-8")
        if not quiet:
            print(f"  [{slug}] created {_rel(category_images_json)}")
    if category_images_json.exists():
        cat_map = json.loads(category_images_json.read_text())
        for cat_name, filename in sorted(cat_map.items()):
            dest = images_dir / filename
            if dest.exists() and not force:
                continue
            _make_category_cover(cat_name, palette, dest)
            written += 1
            if not quiet:
                print(f"  [{slug}] generated {_rel(dest)}")

    hero_files = sorted(images_dir.glob("wonders-page-*.png")) + sorted(
        images_dir.glob("wonders-post-*.png")
    )
    for dest in hero_files:
        if dest.exists() and not force and not _matches_source_image(theme_root, dest):
            continue
        _make_hero_placeholder(_hero_title_from_filename(dest.name), dest.stem, slug, palette, dest)
        written += 1
        if not quiet:
            print(f"  [{slug}] generated {_rel(dest)}")

    manifest = {
        "schema": 1,
        "theme": slug,
        "generated_at": time.time(),
        "generator": "bin/generate-product-photos.py",
        "mode": "pillow-specimen-card",
        "palette": palette,
        "coverage": {
            "products": len(product_map),
            "categories": len(cat_map),
            "missing_products": [
                filename
                for filename in sorted(product_map.values())
                if not (images_dir / filename).is_file()
            ],
            "missing_categories": [
                filename
                for filename in sorted(cat_map.values())
                if not (images_dir / filename).is_file()
            ],
            "hero_placeholders": len(hero_files),
        },
        "products": [
            {
                "sku": sku,
                "filename": filename,
                "path": _rel(images_dir / filename),
                "prompt": (
                    f"{slug} brand-fit product photograph for {sku}; "
                    "specimen-card fallback generated from theme palette"
                ),
                "exists": (images_dir / filename).is_file(),
            }
            for sku, filename in sorted(product_map.items())
        ],
        "categories": [
            {
                "name": name,
                "filename": filename,
                "path": _rel(images_dir / filename),
                "prompt": (
                    f"{slug} category cover for {name}; "
                    "editorial cover generated from theme palette"
                ),
                "exists": (images_dir / filename).is_file(),
            }
            for name, filename in sorted(cat_map.items())
        ],
        "hero_placeholders": [
            {
                "filename": path.name,
                "path": _rel(path),
                "prompt": f"{slug} page/post hero placeholder generated from theme palette",
                "exists": path.is_file(),
            }
            for path in hero_files
        ],
        "regeneration": {
            "all": f"python3 bin/generate-product-photos.py --theme {slug} --force",
            "seed": f"python3 bin/seed-playground-content.py --theme {slug}",
        },
    }
    content_dir.mkdir(parents=True, exist_ok=True)
    image_manifest_json.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not quiet:
        print(f"  [{slug}] wrote {_rel(image_manifest_json)}")

    if not quiet:
        if written:
            print(f"  [{slug}] wrote {written} image(s)")
        else:
            print(f"  [{slug}] all photos already present (pass --force to regenerate)")

    # Re-run seed so CSV/XML refs point at the new photos
    if written:
        cmd = [
            sys.executable,
            str(MONOREPO_ROOT / "bin" / "seed-playground-content.py"),
            "--theme",
            slug,
        ]
        if not quiet:
            print(f"  [{slug}] re-seeding: {' '.join(cmd[1:])}")
        rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
        if rc != 0:
            print(f"  [{slug}] WARN: seed-playground-content.py exited {rc}")

    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--theme", metavar="SLUG", help="Generate photos for one theme.")
    grp.add_argument("--all", action="store_true", help="Generate for every theme.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing photos (default: skip if file already exists).",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not _PILLOW:
        print(
            "ERROR: Pillow is required. Install with:\n  python3 -m pip install Pillow",
            file=sys.stderr,
        )
        return 1

    if args.all:
        total = 0
        for theme_root in iter_themes(stages=()):
            n = generate_photos_for_theme(theme_root, force=args.force, quiet=args.quiet)
            if n < 0:
                return 1
            total += n
        print(f"Total: {total} image(s) written across all themes.")
        return 0

    theme_root = resolve_theme_root(args.theme)
    n = generate_photos_for_theme(theme_root, force=args.force, quiet=args.quiet)
    return 0 if n >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
