#!/usr/bin/env python3
"""Seed each theme's `playground/content/` and `playground/images/` from a
canonical source repo, rewriting every image URL inside the CSV and WXR to
point at that theme's own images folder.

Why this exists:
    Until this refactor, every theme's Playground blueprint pointed
    `importWxr` and the wo-import.php CSV fetch at the same external repo
    (RegionallyFamous/wonders-oddities). That meant every theme served the
    same products with the same product photography, and any theme that
    wanted to diverge -- different copy, different imagery, different
    catalogue -- had nowhere to put it.

    The new layout owns the content per-theme:

        <theme>/playground/content/products.csv
        <theme>/playground/content/content.xml
        <theme>/playground/content/category-images.json
        <theme>/playground/images/*.{png,jpg}

    All image URLs inside CSV + XML are rewritten from
        https://raw.githubusercontent.com/RegionallyFamous/wonders-oddities/main/<file>
    to
        https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<theme>/playground/images/<file>

    so each theme's import populates its WP media library from its own
    images/ folder. After the seed, the per-theme files are the canonical
    source and the upstream wonders-oddities repo is no longer required
    for Playground to boot.

What this script does:
    1. Ensures a local cache of the canonical source repo exists at
       SOURCE_CACHE (clones it on first run, fast-forwards on subsequent
       runs). The default source is RegionallyFamous/wonders-oddities, but
       --source can point at any local directory matching the same shape.
    2. For each theme (auto-discovered via _lib.iter_themes()):
         - Creates `playground/content/` if missing.
         - Copies products.csv -> playground/content/products.csv (if missing
           or --force) and rewrites the source image-URL prefix to the
           per-theme prefix.
         - Copies content.xml  -> playground/content/content.xml  (same).
         - Copies the 6 cat-*.jpg category covers from the legacy shared
           `playground/category-images/` folder into the theme's images/
           folder if they aren't present yet.
         - Copies all wonders-*.png from the source repo into the theme's
           images/ folder, BUT only when the destination file does not
           already exist. This preserves chonk's per-theme generated
           imagery (which already lives in chonk/playground/images/) while
           seeding obel and selvedge with the canonical PNGs. The copy
           also unconditionally skips `wonders-<product-slug>.png` when a
           per-theme `product-wo-<slug>.jpg` photograph is already in the
           destination — those cartoons would only be deleted seconds
           later by the upgrade pass.
         - Runs an UPGRADE pass over the per-theme CSV + WXR after the
           assets are in place: every `wonders-<product-slug>.png` URL is
           rewritten to `product-wo-<slug>.jpg` when the photograph is
           present in the theme's images/ folder. This is what makes the
           Playground render real product photography instead of the
           upstream's flat cartoon placeholders. Page/post hero refs
           (`wonders-page-*.png`, `wonders-post-*.png`) are left alone
           until per-theme photographic equivalents exist.
         - Cleans up `wonders-<product-slug>.png` cartoon files from the
           theme's images/ folder once they are no longer referenced (i.e.
           the upgrade pass already swung the URLs over to the JPGs).
           Page/post cartoons remain on disk because they are still the
           live image for those entries.

    The script is fully idempotent. Re-running it is a no-op once every
    theme is seeded; pass --force to overwrite existing per-theme content
    and images (use this when you intentionally want to re-pull from the
    upstream source).

Usage:
    python3 bin/seed-playground-content.py
    python3 bin/seed-playground-content.py --force
    python3 bin/seed-playground-content.py --source /path/to/local/checkout
    python3 bin/seed-playground-content.py --theme obel
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, iter_themes

# Where to cache the upstream source repo locally between runs. /tmp keeps
# it out of the user's home and out of the monorepo, and survives across
# bin/ script runs within a single OS session.
SOURCE_CACHE = Path("/tmp/wonders-oddities-source")
SOURCE_REPO_URL = "https://github.com/RegionallyFamous/wonders-oddities.git"

# The URL prefix the upstream CSV/XML uses for its image references. Every
# match of this string (anywhere in the file) is rewritten to point at the
# per-theme images folder.
SOURCE_IMAGE_URL_PREFIX = (
    "https://raw.githubusercontent.com/RegionallyFamous/wonders-oddities/main/"
)

# Per-theme image URL template. {theme} is the theme directory slug.
PER_THEME_IMAGE_URL_PREFIX = (
    "https://raw.githubusercontent.com/RegionallyFamous/fifty/main/{theme}/playground/images/"
)

# Filenames inside the source repo that we treat as canonical content.
SOURCE_CSV_FILENAME = "wonders-oddities-products.csv"
SOURCE_XML_FILENAME = "wonders-oddities-content.xml"

# Where the destination files land inside each theme.
DEST_CSV_RELPATH = Path("playground") / "content" / "products.csv"
DEST_XML_RELPATH = Path("playground") / "content" / "content.xml"
DEST_IMAGES_RELDIR = Path("playground") / "images"

# Legacy folder of the 6 category cover JPGs that previously lived shared
# at the monorepo root. We copy them into each theme's images/ folder
# during the seed so the new per-theme layout is self-contained.
LEGACY_CATEGORY_IMAGES_DIR = MONOREPO_ROOT / "playground" / "category-images"

# Canonical source of per-theme product photographs. When a freshly-cloned
# theme is missing a photograph that its inherited templates/patterns
# reference (most notably `patterns/hero-split.php`'s hardcoded
# `product-wo-bottled-morning.jpg`), we copy from this theme so the
# `build` pipeline renders without broken images. The `dress` pipeline
# later regenerates theme-specific photography that overwrites these
# placeholders. See `copy_photo_placeholders` below for the idempotence
# rules — we never clobber a theme's own photographs.
PHOTO_PLACEHOLDER_SOURCE_THEME = "obel"


def ensure_source_cache(source_override: Path | None) -> Path:
    """Return a path to the canonical source repo, cloning or fetching as
    needed. If --source was provided, use that and skip git entirely."""
    if source_override is not None:
        if not source_override.is_dir():
            raise SystemExit(f"--source path does not exist: {source_override}")
        return source_override

    if not SOURCE_CACHE.exists():
        print(f"Cloning {SOURCE_REPO_URL} -> {SOURCE_CACHE} ...")
        subprocess.run(
            ["git", "clone", "--depth", "1", SOURCE_REPO_URL, str(SOURCE_CACHE)],
            check=True,
        )
    else:
        print(f"Updating {SOURCE_CACHE} ...")
        try:
            subprocess.run(
                ["git", "-C", str(SOURCE_CACHE), "fetch", "--depth", "1", "origin", "main"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "-C", str(SOURCE_CACHE), "reset", "--hard", "origin/main"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            # Network may be down; fall back to whatever's already cached.
            print(
                "warn: could not refresh source cache; using existing checkout",
                file=sys.stderr,
            )
    return SOURCE_CACHE


def rewrite_image_urls(text: str, theme_slug: str) -> str:
    """Replace every occurrence of the upstream image-URL prefix with the
    per-theme prefix. Done as a literal string replace -- the upstream
    URLs are a stable known string and we want to avoid regex surprises
    inside the WXR's CDATA blocks."""
    return text.replace(
        SOURCE_IMAGE_URL_PREFIX,
        PER_THEME_IMAGE_URL_PREFIX.format(theme=theme_slug),
    )


_WONDERS_PNG_RE = re.compile(r"wonders-([a-z0-9-]+)\.png")


def upgrade_product_image_refs(text: str, available_images: set[str]) -> tuple[str, int]:
    """Rewrite every `wonders-<slug>.png` reference to `product-wo-<slug>.jpg`
    when the photographic version is present in the theme's images folder.

    Background: the upstream `wonders-oddities` source ships flat cartoon PNGs
    (mug silhouette on yellow, lightning cloud, etc.) AND -- since the per-theme
    image generation work landed -- per-theme photographic JPGs that live
    alongside them under `<theme>/playground/images/product-wo-<slug>.jpg`. The
    upstream CSV/XML still references the cartoons, so without this rewrite
    every theme renders the catalogue with placeholder illustrations even
    though it has real product photography sitting next to them on disk.

    Page/post hero references (`wonders-page-*.png`, `wonders-post-*.png`)
    are deliberately left alone -- their photographic counterparts haven't
    been generated yet, so rewriting them would produce 404s. Once those
    exist, this function will pick them up automatically.

    Returns the rewritten text plus a count of substitutions, so the seeder
    can log a one-line summary per file.
    """

    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        slug = match.group(1)
        if slug.startswith(("page-", "post-")):
            return match.group(0)
        photo = f"product-wo-{slug}.jpg"
        if photo in available_images:
            count += 1
            return photo
        return match.group(0)

    return _WONDERS_PNG_RE.sub(replace, text), count


def copy_text_with_rewrite(src: Path, dst: Path, theme_slug: str, force: bool) -> str:
    """Copy a CSV/XML file, rewriting image URLs to the per-theme prefix.
    Returns 'created' / 'updated' / 'skipped'."""
    if dst.exists() and not force:
        return "skipped"
    dst.parent.mkdir(parents=True, exist_ok=True)
    new_text = rewrite_image_urls(src.read_text(encoding="utf-8"), theme_slug)
    existed = dst.exists()
    dst.write_text(new_text, encoding="utf-8")
    return "updated" if existed else "created"


# Suffixes we'll copy into a theme's images/ folder. Despite the folder
# name, this includes PDFs and audio because the wonders-oddities WXR
# references novelty-product attachments like imaginary-deed.pdf and
# one-hand.wav. Per-theme `images/` is really "every binary attachment the
# CSV or WXR points at". CSV/XML/MD are deliberately excluded -- those are
# content, not assets, and live under content/.
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".wav", ".mp3", ".mp4")


def copy_asset_files(src_dir: Path, dst_dir: Path, force: bool) -> tuple[int, int]:
    """Copy every file in src_dir whose extension is in ASSET_SUFFIXES
    into dst_dir. Returns (copied, skipped) counts. Existing destination
    files are left alone unless force=True -- this preserves per-theme
    generated imagery (e.g. chonk/playground/images/).

    One specific source file is filtered out unconditionally:
    `wonders-<product-slug>.png` whenever a `product-wo-<slug>.jpg`
    photograph is already present in the destination. The cartoon would
    otherwise be re-copied on every run and immediately deleted by
    `cleanup_unused_product_cartoons`, which is correct but wastes I/O
    and makes the seeder log misleading. The filter does NOT apply to
    `wonders-page-*.png` / `wonders-post-*.png` (those have no photo
    equivalents yet — see the Phase B follow-up to generate them).
    """
    if not src_dir.is_dir():
        return (0, 0)
    dst_dir.mkdir(parents=True, exist_ok=True)
    available = {p.name for p in dst_dir.iterdir()} if dst_dir.exists() else set()
    copied = 0
    skipped = 0
    for entry in sorted(src_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in ASSET_SUFFIXES:
            continue
        m = re.match(r"wonders-([a-z0-9-]+)\.png$", entry.name)
        if m and not m.group(1).startswith(("page-", "post-")):
            slug = m.group(1)
            if f"product-wo-{slug}.jpg" in available:
                skipped += 1
                continue
        dst = dst_dir / entry.name
        if dst.exists() and not force:
            skipped += 1
            continue
        shutil.copy2(entry, dst)
        copied += 1
    return (copied, skipped)


def copy_photo_placeholders(
    source_theme: str,
    target_theme: str,
    dst_dir: Path,
) -> tuple[int, int]:
    """Copy per-theme product photographs (`product-wo-*.jpg`) from a
    canonical source theme into `dst_dir`, filling gaps without ever
    clobbering a file the target already owns.

    Why this exists:
        `bin/clone.py` copies obel's `patterns/` verbatim. Several of
        those patterns — most notably `hero-split.php` — hardcode
        `product-wo-<slug>.jpg` URLs that resolve against the TARGET
        theme's `playground/images/` folder. A freshly-cloned theme's
        images folder has only upstream `wonders-*.png` cartoons, so
        the pattern's hero image 404s and `bin/snap.py`'s
        `broken-image` heuristic (intentionally, 0 cells allowlisted)
        blocks `bin/design.py build` on something that is really a
        missing-placeholder rather than a structural defect. The
        placeholder makes `build` pass on a fresh clone; the `dress`
        pipeline later regenerates theme-specific photography that
        overwrites these files.

    Idempotence:
        - A re-run on an already-seeded theme is a strict no-op: every
          target file already exists, so every copy short-circuits on
          the `dst.exists()` guard.
        - A re-run on a theme that has ALREADY shipped its own real
          photography (chonk / foundry / shipping themes) is also a
          no-op for the same reason — we never overwrite a file.
        - Seeding the source theme onto itself short-circuits before
          any file I/O; guards a subtle "copy obel's photos onto obel"
          infinite-refresh footgun.

    Returns `(copied, skipped)` so the seeder log can stay one line
    per theme.
    """
    if target_theme == source_theme:
        return (0, 0)
    source_images = MONOREPO_ROOT / source_theme / "playground" / "images"
    if not source_images.is_dir():
        return (0, 0)
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    for entry in sorted(source_images.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.startswith("product-wo-"):
            continue
        if entry.suffix.lower() != ".jpg":
            continue
        dst = dst_dir / entry.name
        if dst.exists():
            skipped += 1
            continue
        shutil.copy2(entry, dst)
        copied += 1
    return (copied, skipped)


def seed_theme(theme_dir: Path, source_dir: Path, force: bool) -> None:
    slug = theme_dir.name
    csv_src = source_dir / SOURCE_CSV_FILENAME
    xml_src = source_dir / SOURCE_XML_FILENAME

    if not csv_src.is_file() or not xml_src.is_file():
        raise SystemExit(
            f"error: source missing CSV or XML at {source_dir} "
            f"(expected {SOURCE_CSV_FILENAME} and {SOURCE_XML_FILENAME})"
        )

    csv_status = copy_text_with_rewrite(csv_src, theme_dir / DEST_CSV_RELPATH, slug, force)
    xml_status = copy_text_with_rewrite(xml_src, theme_dir / DEST_XML_RELPATH, slug, force)

    images_dir = theme_dir / DEST_IMAGES_RELDIR
    asset_copied, asset_skipped = copy_asset_files(source_dir, images_dir, force)
    cat_copied, cat_skipped = copy_asset_files(LEGACY_CATEGORY_IMAGES_DIR, images_dir, force)

    # Photo placeholders: copy per-theme product photographs from the
    # canonical source theme (obel) into this theme's images folder,
    # skipping anything the target already has. Runs BEFORE the upgrade
    # pass so the newly-copied JPGs enter the `available` set and the
    # upgrade pass can rewrite `wonders-<slug>.png` catalogue refs to
    # `product-wo-<slug>.jpg` — meaning a freshly-cloned theme ships a
    # fully-photographed catalogue on first `build`, not a half-photo
    # half-cartoon mishmash. See `copy_photo_placeholders` for
    # idempotence guarantees.
    photo_copied, photo_skipped = copy_photo_placeholders(
        PHOTO_PLACEHOLDER_SOURCE_THEME, slug, images_dir
    )

    # Upgrade pass: run AFTER assets are in place, so that
    # upgrade_product_image_refs can see which `product-wo-<slug>.jpg`
    # photographs are actually present and only rewrite refs that have a
    # real file to point at. Idempotent — re-running on already-upgraded
    # files is a no-op (no `wonders-<product-slug>.png` left to match).
    available = {p.name for p in images_dir.iterdir()} if images_dir.exists() else set()
    csv_upgraded = upgrade_text_file(theme_dir / DEST_CSV_RELPATH, available)
    xml_upgraded = upgrade_text_file(theme_dir / DEST_XML_RELPATH, available)
    cleaned = cleanup_unused_product_cartoons(images_dir)

    print(
        f"{slug:>10}  csv={csv_status:<8} xml={xml_status:<8} "
        f"assets={asset_copied}+{asset_skipped}-skip  "
        f"cat={cat_copied}+{cat_skipped}-skip  "
        f"photos={photo_copied}+{photo_skipped}-skip  "
        f"upgrade=csv:{csv_upgraded}/xml:{xml_upgraded}  "
        f"cleaned-cartoons={cleaned}"
    )


def upgrade_text_file(path: Path, available_images: set[str]) -> int:
    """Apply `upgrade_product_image_refs` to a file in place. Returns the
    substitution count (0 if the file was already upgraded or absent)."""
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8")
    new_text, n = upgrade_product_image_refs(text, available_images)
    if n > 0 and new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return n


def cleanup_unused_product_cartoons(images_dir: Path) -> int:
    """Delete `wonders-<product-slug>.png` files that have a photographic
    `product-wo-<slug>.jpg` sibling — the seeder rewrites every product
    reference away from these PNGs in the same pass, so the cartoons are
    pure dead weight after upgrade. Page/post hero PNGs are preserved
    because their references are NOT rewritten (no photo equivalents yet).
    """
    if not images_dir.is_dir():
        return 0
    available = {p.name for p in images_dir.iterdir()}
    deleted = 0
    for entry in sorted(images_dir.iterdir()):
        m = re.match(r"wonders-([a-z0-9-]+)\.png$", entry.name)
        if not m:
            continue
        slug = m.group(1)
        if slug.startswith(("page-", "post-")):
            continue
        if f"product-wo-{slug}.jpg" in available:
            entry.unlink()
            deleted += 1
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Path to a local checkout of the canonical content source. "
            "Defaults to cloning RegionallyFamous/wonders-oddities to "
            f"{SOURCE_CACHE}."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite existing per-theme content/ and images/ files. "
            "Use this only when you intentionally want to re-pull from "
            "the upstream source -- the per-theme files are the canonical "
            "source for that theme after the initial seed."
        ),
    )
    parser.add_argument(
        "--theme",
        default=None,
        help="Limit to a single theme (default: all themes).",
    )
    args = parser.parse_args()

    source_dir = ensure_source_cache(args.source)

    # Iterate across every stage (including `incubating`/`design`) so
    # that freshly-cloned themes — which `bin/clone.py` writes as
    # `stage: incubating` — are visible to the seeder as well. Without
    # this, `iter_themes()`'s default shipping-only filter drops the
    # brand-new theme and the chicken-and-egg failure mode is
    # `bin/design.py` reporting `theme '<slug>' not found` on a theme
    # it just created two phases earlier (see the design-batch.py
    # reship failure of 2026-04-27 for the worked example).
    themes = list(iter_themes(stages=()))
    if args.theme:
        themes = [t for t in themes if t.name == args.theme]
        if not themes:
            raise SystemExit(f"error: theme '{args.theme}' not found")
    if not themes:
        raise SystemExit("error: no themes found in monorepo")

    print(f"Seeding from {source_dir}\n")
    for theme_dir in themes:
        seed_theme(theme_dir, source_dir, force=args.force)
    print(
        "\nDone. Run `python3 bin/sync-playground.py` next to refresh each "
        "theme's blueprint with the new content base URL."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
