"""Wiring smoke test for conftest.py.

Verifies that:
  - `bin/` is on sys.path so `import check` and `import _lib` work
  - the `minimal_theme` fixture writes a tree pytest can re-read
  - the `bind_check_root` fixture rebinds `check.ROOT`
  - `check.iter_themes()` honors the `monorepo` fixture's
    monkeypatched `_lib.MONOREPO_ROOT`

Kept intentionally tiny so a regression in fixture wiring shows up
on the very first failing test instead of cascading through the
rest of the suite.
"""

from __future__ import annotations

from pathlib import Path


def test_bin_is_importable():
    import _lib  # noqa: F401  (sanity import — fails fast on path tweak regression)
    import check  # noqa: F401

    assert callable(check.check_json_validity)
    assert callable(_lib.iter_themes)


def test_minimal_theme_has_required_files(minimal_theme: Path):
    assert (minimal_theme / "theme.json").is_file()
    assert (minimal_theme / "style.css").is_file()
    assert (minimal_theme / "functions.php").is_file()
    assert (minimal_theme / "templates" / "index.html").is_file()
    assert (minimal_theme / "parts" / "header.html").is_file()
    assert (minimal_theme / "parts" / "footer.html").is_file()


def test_bind_check_root_swaps_root(minimal_theme: Path, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert minimal_theme == check.ROOT


def test_monorepo_fixture_yields_two_themes(monorepo):
    import _lib

    themes = list(_lib.iter_themes())
    names = sorted(t.name for t in themes)
    assert names == ["chonk", "obel"]
    assert monorepo["root"] == _lib.MONOREPO_ROOT
