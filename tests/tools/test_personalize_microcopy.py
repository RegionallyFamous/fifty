"""Tests for `bin/personalize-microcopy.py`.

The contract:

1. The substitution map is cascade-safe — no replacement contains its
   own needle as a substring. Otherwise re-running the script would
   duplicate the replacement suffix every time. (The script itself has
   a runtime guard; this test is a belt-and-braces unit test.)
2. `apply_for_theme` applied twice in a row produces identical output
   on the second run — the substitutions are pure text replacements,
   so idempotence is a first-class invariant.
3. Running against a theme whose slug is NOT in a particular VARIANTS
   entry leaves the file unchanged for that entry.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def pm():
    """Import `bin/personalize-microcopy.py` under an importable name."""
    bin_dir = Path(__file__).resolve().parent.parent.parent / "bin"
    spec = importlib.util.spec_from_file_location(
        "personalize_microcopy", bin_dir / "personalize-microcopy.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_variants_are_cascade_safe(pm):
    """No replacement contains its needle as a substring.

    If a pair like {"received": "received, with thanks"} shipped,
    str.replace would find "received" inside its own previous output
    on re-run and keep appending ", with thanks" forever.
    """
    bad: list[tuple[str, str, str]] = []
    for needle, by_theme in pm.VARIANTS.items():
        for theme, repl in by_theme.items():
            if needle in repl:
                bad.append((needle, theme, repl))
    assert not bad, (
        "cascade-hazard substitutions present — each of these would "
        f"cascade-duplicate on re-run:\n{bad}"
    )


def test_apply_for_theme_is_idempotent(pm, tmp_path: Path):
    """Running apply_for_theme twice produces identical output on run #2."""
    theme = tmp_path / "aero"
    (theme / "templates").mkdir(parents=True)
    (theme / "parts").mkdir()
    (theme / "patterns").mkdir()

    needle, by_theme = next(iter(pm.VARIANTS.items()))
    assert "aero" in by_theme, f"expected VARIANTS[{needle!r}] to define an aero variant"
    template = theme / "templates" / "order-confirmation.html"
    template.write_text(
        f"<!-- wp:heading --><h1>{needle}</h1><!-- /wp:heading -->\n",
        encoding="utf-8",
    )

    files1, subs1 = pm.apply_for_theme(theme, dry_run=False)
    assert files1 == 1 and subs1 >= 1
    first = template.read_bytes()

    files2, subs2 = pm.apply_for_theme(theme, dry_run=False)
    assert files2 == 0 and subs2 == 0, "apply_for_theme re-substituted on run #2 — cascade hazard"
    second = template.read_bytes()
    assert first == second


def test_apply_for_theme_respects_slug(pm, tmp_path: Path):
    """Theme slug drives which replacement is used.

    Using a slug that isn't registered in any VARIANTS entry is a
    total no-op.
    """
    theme = tmp_path / "unknown-slug"
    (theme / "templates").mkdir(parents=True)
    (theme / "parts").mkdir()
    (theme / "patterns").mkdir()

    needle = next(iter(pm.VARIANTS))
    original = f"<p>{needle}</p>\n"
    (theme / "templates" / "index.html").write_text(original, encoding="utf-8")

    files, subs = pm.apply_for_theme(theme, dry_run=False)
    assert files == 0 and subs == 0
    assert (theme / "templates" / "index.html").read_text() == original
