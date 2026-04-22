"""Tests for `bin/check.py:check_no_placeholder_product_images`.

The seeder (`bin/seed-playground-content.py`) pulls the upstream
`wonders-oddities` catalogue with flat illustrated cartoons (mug
silhouette on yellow, etc.) under `wonders-<slug>.png`. After per-theme
photographs are dropped in as `product-wo-<slug>.jpg`, the seeder
rewrites every CSV/XML reference to point at the photo and deletes the
cartoon. The fail mode this check guards: the upgrade pass never runs
(or never had photos to point at), so the live demo paints the
catalogue with the upstream cartoons.

Real-world hits this check catches:
  * aero shipped with 30 placeholder cartoon refs and zero bespoke
    photos on disk.
  * lysholm had every photograph on disk but its CSV was never
    re-upgraded, so it ALSO shipped with the cartoons.

The shape of `playground/content/` exercised here mirrors the real
layout: a CSV that lists product images under the
`raw.githubusercontent.com/RegionallyFamous/fifty/main/<slug>/playground/images/`
prefix, optionally a content.xml with the same refs in CDATA, and a
`playground/images/` folder that may or may not contain the
matching `product-wo-<slug>.jpg` photos.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

CSV_HEADER = "ID,Type,SKU,Name,Images\n"


def _seed_csv(theme_root: Path, refs: list[str]) -> None:
    """Write a minimal `playground/content/products.csv` whose `Images`
    column points at each ref under this theme's images folder."""
    rows = [CSV_HEADER]
    for i, ref in enumerate(refs, start=1001):
        url = f"https://raw.githubusercontent.com/RegionallyFamous/fifty/main/{theme_root.name}/playground/images/{ref}"
        rows.append(f"{i},simple,WO-{i},Product {i},{url}\n")
    csv_path = theme_root / "playground" / "content" / "products.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("".join(rows), encoding="utf-8")


def _seed_xml(theme_root: Path, refs: list[str]) -> None:
    """Write a minimal `playground/content/content.xml` referencing
    each ref as a `<wp:attachment_url>`."""
    items = "\n".join(
        f"  <item><wp:attachment_url>https://raw.githubusercontent.com/RegionallyFamous/fifty/main/{theme_root.name}/playground/images/{r}</wp:attachment_url></item>"
        for r in refs
    )
    xml_path = theme_root / "playground" / "content" / "content.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(
        textwrap.dedent(
            f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <rss version="2.0"><channel>
            {items}
            </channel></rss>
            """
        ),
        encoding="utf-8",
    )


def _put_image(theme_root: Path, name: str) -> None:
    """Drop a 1-byte placeholder file at `playground/images/<name>`."""
    p = theme_root / "playground" / "images" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00")


def test_passes_when_csv_and_disk_are_fully_bespoke(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    refs = ["product-wo-bottled-morning.jpg", "product-wo-silence-jar.jpg"]
    _seed_csv(minimal_theme, refs)
    for r in refs:
        _put_image(minimal_theme, r)
    result = check.check_no_placeholder_product_images()
    assert result.passed, result.details


def test_fails_when_csv_references_placeholder_cartoon(minimal_theme, bind_check_root):
    """The aero failure mode: CSV points at upstream cartoons and no
    bespoke photos exist on disk to upgrade to."""
    check = bind_check_root(minimal_theme)
    _seed_csv(minimal_theme, ["wonders-bottled-morning.png", "wonders-silence-jar.png"])
    result = check.check_no_placeholder_product_images()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "placeholder" in joined.lower()
    assert "wonders-bottled-morning.png" in joined or "wonders-silence-jar.png" in joined
    assert "Generate the missing photos" in joined


def test_fails_when_csv_has_placeholder_but_disk_has_photo(minimal_theme, bind_check_root):
    """The lysholm failure mode: photos exist on disk but the CSV's
    upgrade pass never ran. The check should call out the seeder
    re-run, not ask the author to regenerate photos."""
    check = bind_check_root(minimal_theme)
    _seed_csv(minimal_theme, ["wonders-bottled-morning.png"])
    _put_image(minimal_theme, "product-wo-bottled-morning.jpg")
    result = check.check_no_placeholder_product_images()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "seeder's upgrade pass never ran" in joined
    assert "seed-playground-content.py" in joined


def test_fails_when_csv_references_bespoke_jpg_missing_on_disk(minimal_theme, bind_check_root):
    """If the CSV points at `product-wo-foo.jpg` but the file is missing,
    the live demo will 404 on that URL — the check should call that out
    even when no placeholder cartoons remain."""
    check = bind_check_root(minimal_theme)
    _seed_csv(minimal_theme, ["product-wo-bottled-morning.jpg"])
    result = check.check_no_placeholder_product_images()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "product-wo-bottled-morning.jpg" in joined
    assert "404" in joined or "missing" in joined.lower()


def test_passes_when_csv_references_only_page_post_placeholders(minimal_theme, bind_check_root):
    """Page/post hero refs (`wonders-page-*.png`, `wonders-post-*.png`)
    have no `product-wo-*` counterpart and live a separate generation
    track — the check is not supposed to flag them."""
    check = bind_check_root(minimal_theme)
    _seed_csv(
        minimal_theme,
        [
            "wonders-page-home.png",
            "wonders-post-fog-season.png",
            "product-wo-bottled-morning.jpg",
        ],
    )
    _put_image(minimal_theme, "product-wo-bottled-morning.jpg")
    result = check.check_no_placeholder_product_images()
    assert result.passed, result.details


def test_skips_when_no_products_csv_exists(minimal_theme, bind_check_root):
    """A theme without a Playground demo (no products.csv) has nothing
    to enforce — the check should skip cleanly."""
    check = bind_check_root(minimal_theme)
    result = check.check_no_placeholder_product_images()
    assert result.skipped, result.details


def test_skips_when_csv_has_no_product_image_refs(minimal_theme, bind_check_root):
    """An empty (header-only) CSV with no image refs has nothing to
    judge against — neither bespoke nor placeholder. Skip rather than
    pass to make the empty state visible in the gate output."""
    check = bind_check_root(minimal_theme)
    csv_path = minimal_theme / "playground" / "content" / "products.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(CSV_HEADER, encoding="utf-8")
    result = check.check_no_placeholder_product_images()
    assert result.skipped, result.details


def test_xml_placeholder_refs_are_also_caught(minimal_theme, bind_check_root):
    """`playground/content/content.xml` carries product image refs in
    CDATA blocks (the WXR payload). The check has to scan it too —
    a CSV-clean theme can still ship cartoons via the WXR side."""
    check = bind_check_root(minimal_theme)
    _seed_csv(minimal_theme, ["product-wo-bottled-morning.jpg"])
    _put_image(minimal_theme, "product-wo-bottled-morning.jpg")
    _seed_xml(minimal_theme, ["wonders-bottled-morning.png"])
    result = check.check_no_placeholder_product_images()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "wonders-bottled-morning.png" in joined
