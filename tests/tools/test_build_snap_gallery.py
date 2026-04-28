"""Contract tests for `bin/build-snap-gallery.py` — ensure the snap
gallery picks up every real theme on disk automatically, even when a new
theme isn't listed in `snap_config.THEME_ORDER`.

Regression guard: Foundry was added to the repo after THEME_ORDER was
written, and the previous filter (`[t for t in THEME_ORDER if ...]`)
silently dropped it — the picker at demo.regionallyfamous.com/snaps/
rendered five cards with Foundry's baseline PNGs sitting unreferenced
on disk. Auto-discovery is how we stop that from happening again.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gallery():
    """Load `bin/build-snap-gallery.py` as a module. Hyphenated filename,
    so importlib.spec is the only option."""
    spec = importlib.util.spec_from_file_location(
        "build_snap_gallery", ROOT / "bin" / "build-snap-gallery.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_themes() -> set[str]:
    """Every *shipping* theme folder on disk. The gallery intentionally
    excludes `incubating` themes (WIP clones whose baselines haven't been
    shipped yet); the regression guard checks only that every SHIPPING
    theme lands in the picker, which matches the contract
    `bin/build-snap-gallery.py._discover_themes()` enforces."""
    import sys

    sys.path.insert(0, str(ROOT / "bin"))
    from _readiness import STAGE_SHIPPING, load_readiness

    return {
        p.parent.name
        for p in ROOT.glob("*/theme.json")
        if (p.parent / "playground" / "blueprint.json").exists()
        and load_readiness(p.parent).stage == STAGE_SHIPPING
    }


def test_discover_themes_covers_every_theme_on_disk(gallery) -> None:
    """Every theme folder with a theme.json + blueprint.json must land in
    the gallery. If this fails after adding a new theme, the picker at
    demo.regionallyfamous.com/snaps/ is about to silently drop it."""
    discovered = set(gallery._discover_themes())
    real = _real_themes()
    missing = real - discovered
    assert not missing, (
        f"build-snap-gallery.py._discover_themes() dropped {sorted(missing)}. "
        f"Any folder with theme.json + playground/blueprint.json must land in "
        f"the gallery automatically — the picker can't pretend themes don't exist."
    )


def test_discover_themes_honours_theme_order(gallery) -> None:
    """Themes listed in `snap_config.THEME_ORDER` must appear BEFORE any
    auto-discovered extras, and must appear in THEME_ORDER's order. This
    keeps the picker's canonical magazine-cover ordering stable across
    commits while still letting new themes show up without a config edit."""
    from snap_config import THEME_ORDER

    discovered = gallery._discover_themes()
    real = _real_themes()
    want_prefix = [t for t in THEME_ORDER if t in real]
    assert discovered[: len(want_prefix)] == want_prefix, (
        f"THEME_ORDER prefix drifted: expected {want_prefix}, got {discovered[: len(want_prefix)]}."
    )


def test_every_discovered_theme_has_a_blurb(gallery) -> None:
    """Every theme in the gallery must render with SOME blurb — either
    hand-crafted in `THEME_BLURBS` or auto-extracted from design-intent.md.
    Empty blurbs make the picker card look broken (italic paragraph
    collapses to a 0-height line), so we block a theme landing without
    either source of copy."""
    for theme in gallery._discover_themes():
        blurb = gallery._blurb_for(theme)
        assert blurb, (
            f"No blurb available for theme '{theme}'. Add an entry to "
            f"bin/build-snap-gallery.py::THEME_BLURBS, OR write a "
            f"first-line description in {theme}/design-intent.md (or BRIEF.md)."
        )
