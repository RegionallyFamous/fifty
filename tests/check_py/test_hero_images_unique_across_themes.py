"""Tests for `bin/check.py:check_hero_images_unique_across_themes`.

Sister check to `check_product_images_unique_across_themes`. Owns
the `wonders-page-*.png` / `wonders-post-*.png` slot.

Real-world incident this check exists to catch:

* **The selvedge shape (hero copy-paste from clone):** when selvedge
  was cloned from obel, every `wonders-post-*.png` (20 files) and
  `wonders-page-*.png` (8 files) was copied verbatim. Selvedge then
  shipped its bespoke product photos (so
  `check_product_images_unique_across_themes` passed) but the
  journal and page heroes painted obel's bright coral geometric
  placeholders inside selvedge's dark editorial cinematic theme.
  The visual mismatch was glaring on the live demo and invisible
  to every other check.

The check sha256-hashes every theme's hero placeholders and fails
when any two themes share the same digest.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_post(theme_root: Path, slug: str, content: bytes) -> Path:
    p = theme_root / "playground" / "images" / f"wonders-post-{slug}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _write_page(theme_root: Path, slug: str, content: bytes) -> Path:
    p = theme_root / "playground" / "images" / f"wonders-page-{slug}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


@pytest.fixture
def two_themes(monorepo, monkeypatch):
    import check  # noqa: WPS433

    return monorepo, check


def test_passes_when_every_hero_is_byte_unique(two_themes):
    monorepo, check = two_themes
    _write_post(monorepo["obel"], "welcome", b"OBEL_POST_001")
    _write_post(monorepo["chonk"], "welcome", b"CHONK_POST_001")
    _write_page(monorepo["obel"], "home", b"OBEL_PAGE_001")
    _write_page(monorepo["chonk"], "home", b"CHONK_PAGE_001")
    result = check.check_hero_images_unique_across_themes()
    assert result.passed, result.details
    joined = "\n".join(result.details)
    assert "byte-unique" in joined
    assert "4" in joined  # 4 heroes hashed total


def test_fails_when_one_post_hero_leaks(two_themes):
    """A single post hero copied between two themes must trip the check."""
    monorepo, check = two_themes
    same_bytes = b"COPIED_POST_HERO"
    _write_post(monorepo["obel"], "welcome", same_bytes)
    _write_post(monorepo["chonk"], "welcome", same_bytes)
    _write_post(monorepo["obel"], "year-one", b"OBEL_OK")
    _write_post(monorepo["chonk"], "year-one", b"CHONK_OK")
    result = check.check_hero_images_unique_across_themes()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "byte-identical" in joined
    assert "obel/wonders-post-welcome.png" in joined
    assert "chonk/wonders-post-welcome.png" in joined


def test_fails_when_every_hero_leaks_the_selvedge_shape(two_themes):
    """The selvedge shape: an entire hero set was copy-pasted from
    another theme without regeneration. All 20 posts + 8 pages leak."""
    monorepo, check = two_themes
    for i in range(5):
        same = f"COPIED_POST_{i}".encode()
        _write_post(monorepo["obel"], f"slug-{i}", same)
        _write_post(monorepo["chonk"], f"slug-{i}", same)
    for i in range(3):
        same = f"COPIED_PAGE_{i}".encode()
        _write_page(monorepo["obel"], f"page-{i}", same)
        _write_page(monorepo["chonk"], f"page-{i}", same)
    result = check.check_hero_images_unique_across_themes()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "8" in joined  # 8 leaked files reported
    assert "[chonk, obel]" in joined or "[obel, chonk]" in joined


def test_fails_when_a_single_page_hero_leaks(two_themes):
    """Pages are checked too, not just posts."""
    monorepo, check = two_themes
    same_bytes = b"SHARED_PAGE_HERO"
    _write_page(monorepo["obel"], "home", same_bytes)
    _write_page(monorepo["chonk"], "home", same_bytes)
    _write_page(monorepo["obel"], "about", b"OBEL_ABOUT")
    _write_page(monorepo["chonk"], "about", b"CHONK_ABOUT")
    result = check.check_hero_images_unique_across_themes()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "wonders-page-home.png" in joined


def test_remediation_hint_names_both_themes_and_points_at_generator(two_themes):
    """The remediation message must call out both themes involved and
    point at the canonical generator path so the human knows where to
    look. The selvedge incident took a screenshot from the user to
    surface; the message has to teach the reader the right tooling."""
    monorepo, check = two_themes
    same = b"LEAK"
    _write_post(monorepo["obel"], "welcome", same)
    _write_post(monorepo["chonk"], "welcome", same)
    result = check.check_hero_images_unique_across_themes()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "[chonk, obel]" in joined
    assert "playground-imagery.mdc" in joined
    assert "generate-images.py" in joined
    assert "style.css" in joined
    assert "Regenerate" in joined


def test_skips_when_no_themes_have_any_hero_placeholders(two_themes):
    """A monorepo without any wonders-*.png placeholders has nothing
    to enforce -- skip cleanly so the check doesn't false-pass on
    an empty repo."""
    _, check = two_themes
    result = check.check_hero_images_unique_across_themes()
    assert result.skipped, result.details


def test_passes_when_only_one_theme_ships_heroes(two_themes):
    """One theme with heroes, one without -- nothing to compare,
    pass cleanly."""
    monorepo, check = two_themes
    _write_post(monorepo["obel"], "welcome", b"OBEL_001")
    _write_page(monorepo["obel"], "home", b"OBEL_002")
    result = check.check_hero_images_unique_across_themes()
    assert result.passed, result.details


def test_product_photos_are_not_checked_here(two_themes):
    """`product-wo-*.jpg` is the sister check's territory; identical
    product photos across themes MUST NOT trip this check (and vice
    versa). Splitting the two keeps remediation messages targeted."""
    monorepo, check = two_themes
    same_product = b"SHARED_PRODUCT_PHOTO"
    (monorepo["obel"] / "playground" / "images" / "product-wo-bottled.jpg").parent.mkdir(
        parents=True, exist_ok=True
    )
    (monorepo["obel"] / "playground" / "images" / "product-wo-bottled.jpg").write_bytes(
        same_product
    )
    (monorepo["chonk"] / "playground" / "images" / "product-wo-bottled.jpg").write_bytes(
        same_product
    )
    _write_post(monorepo["obel"], "welcome", b"OBEL_OK")
    _write_post(monorepo["chonk"], "welcome", b"CHONK_OK")
    result = check.check_hero_images_unique_across_themes()
    assert result.passed, result.details
