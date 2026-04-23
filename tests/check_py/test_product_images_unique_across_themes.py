"""Tests for `bin/check.py:check_product_images_unique_across_themes`.

Two real-world copy-paste leaks this check exists to catch:

* **The aero shape (untracked-leftover):** a session generated some
  bespoke photos for a new theme but for 7 product slugs the
  generation step was skipped, leaving the previous-theme's
  scratch-copies in `aero/playground/images/`. Those 7 files were
  byte-identical to the matching `selvedge/playground/images/`
  files. `git status` showed 30 added files and looked complete.

* **The lysholm shape (theme-init copy-paste):** when lysholm was
  cloned from obel as a starting point, its entire
  `playground/images/` folder was copied verbatim. All 30
  `product-wo-<slug>.jpg` files were byte-identical to obel's. The
  catalogue rendered with obel's quiet-editorial photography while
  the rest of the theme tried to be Nordic home-goods.

The check hashes every theme's `playground/images/product-wo-*.jpg`
and fails when any two themes share the same sha256.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_photo(theme_root: Path, slug: str, content: bytes) -> Path:
    p = theme_root / "playground" / "images" / f"product-wo-{slug}.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


@pytest.fixture
def two_themes(monorepo, monkeypatch):
    """Two-theme synthetic monorepo with `playground/images/` ready
    for `product-wo-*.jpg` files. Reuses the `monorepo` fixture from
    `tests/conftest.py` (which already patches MONOREPO_ROOT +
    iter_themes)."""
    import check  # noqa: WPS433

    return monorepo, check


def test_passes_when_every_photo_is_byte_unique(two_themes):
    monorepo, check = two_themes
    _write_photo(monorepo["obel"], "bottled-morning", b"OBEL_BYTES_001")
    _write_photo(monorepo["chonk"], "bottled-morning", b"CHONK_BYTES_001")
    _write_photo(monorepo["obel"], "silence-jar", b"OBEL_BYTES_002")
    _write_photo(monorepo["chonk"], "silence-jar", b"CHONK_BYTES_002")
    result = check.check_product_images_unique_across_themes()
    assert result.passed, result.details
    joined = "\n".join(result.details)
    assert "byte-unique" in joined
    assert "4" in joined  # 4 photos hashed


def test_fails_when_one_slug_is_byte_identical_across_themes(two_themes):
    """The aero shape: a single slug leaked between two themes."""
    monorepo, check = two_themes
    same_bytes = b"SCRATCH_COPY_BYTES"
    _write_photo(monorepo["obel"], "bottled-morning", same_bytes)
    _write_photo(monorepo["chonk"], "bottled-morning", same_bytes)
    _write_photo(monorepo["obel"], "silence-jar", b"OBEL_OK")
    _write_photo(monorepo["chonk"], "silence-jar", b"CHONK_OK")
    result = check.check_product_images_unique_across_themes()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "byte-identical" in joined
    assert "obel/product-wo-bottled-morning.jpg" in joined
    assert "chonk/product-wo-bottled-morning.jpg" in joined
    assert "Regenerate" in joined


def test_fails_when_every_slug_is_byte_identical_across_themes(two_themes):
    """The lysholm shape: an entire `playground/images/` folder was
    copy-pasted from another theme without regeneration. Every slug
    leaks."""
    monorepo, check = two_themes
    for slug in ["bottled-morning", "silence-jar", "moon-dust"]:
        same_bytes = f"COPIED_{slug}".encode()
        _write_photo(monorepo["obel"], slug, same_bytes)
        _write_photo(monorepo["chonk"], slug, same_bytes)
    result = check.check_product_images_unique_across_themes()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "3" in joined  # 3 leaked files
    assert "[chonk, obel]" in joined or "[obel, chonk]" in joined.replace(", ", ", ")


def test_remediation_hint_names_both_themes_and_prompts_a_choice(two_themes):
    """The error message has to call out BOTH themes involved (the
    check can't infer which is the copier vs. the original without
    git context), and prompt the user to regenerate whichever is
    actually the duplicate. The hint should mention `style.css` as
    the source-of-truth for each theme's visual voice."""
    monorepo, check = two_themes
    same_bytes = b"LEAK"
    _write_photo(monorepo["obel"], "bottled-morning", same_bytes)
    _write_photo(monorepo["chonk"], "bottled-morning", same_bytes)
    result = check.check_product_images_unique_across_themes()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "[chonk, obel]" in joined
    assert "style.css" in joined
    assert "Regenerate" in joined
    assert "newer one" in joined or "copier" in joined


def test_skips_when_no_themes_have_any_product_photos(two_themes):
    """A monorepo without any product photographs (brand-new clone,
    no Playground demo wired up yet) has nothing to enforce."""
    _, check = two_themes
    result = check.check_product_images_unique_across_themes()
    assert result.skipped, result.details


def test_passes_when_only_one_theme_ships_product_photos(two_themes):
    """One theme with photos, one without -> nothing to compare,
    pass cleanly."""
    monorepo, check = two_themes
    _write_photo(monorepo["obel"], "bottled-morning", b"OBEL_001")
    _write_photo(monorepo["obel"], "silence-jar", b"OBEL_002")
    result = check.check_product_images_unique_across_themes()
    assert result.passed, result.details


def test_page_post_hero_placeholders_are_not_checked(two_themes):
    """Page/post hero refs (`wonders-page-*.png`, `wonders-post-*.png`)
    live on a separate generation track and don't have product
    counterparts. They MUST NOT be hashed by THIS check -- the
    sister check `check_hero_images_unique_across_themes` is the one
    that owns hero uniqueness (see
    `tests/check_py/test_hero_images_unique_across_themes.py`).
    Splitting the two means a hero leak fails its own check with a
    targeted remediation message instead of muddying the product
    photo signal."""
    monorepo, check = two_themes
    # Identical page heroes across both themes -- should be ignored.
    same_bytes = b"PAGE_HERO_SHARED"
    page_a = monorepo["obel"] / "playground" / "images" / "wonders-page-home.png"
    page_b = monorepo["chonk"] / "playground" / "images" / "wonders-page-home.png"
    page_a.parent.mkdir(parents=True, exist_ok=True)
    page_b.parent.mkdir(parents=True, exist_ok=True)
    page_a.write_bytes(same_bytes)
    page_b.write_bytes(same_bytes)
    # And one bespoke product photo each (must be unique).
    _write_photo(monorepo["obel"], "bottled-morning", b"OBEL_OK")
    _write_photo(monorepo["chonk"], "bottled-morning", b"CHONK_OK")
    result = check.check_product_images_unique_across_themes()
    assert result.passed, result.details
