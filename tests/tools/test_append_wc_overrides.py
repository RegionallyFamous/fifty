"""Idempotence + safety tests for `bin/append-wc-overrides.py`.

The contract:

1. `append_for(theme)` is idempotent — when every sentinel is already
   present in `<theme>/theme.json`, the function is a no-op and returns
   a status where every chunk reports "skip".
2. When the base anchor (`/* /archive-product polish */`) is missing,
   the chunk reports a failure rather than silently splicing into the
   wrong spot. This guards against pasting WooCommerce CSS into themes
   that haven't landed the archive-polish block yet.
3. Running against the real monorepo themes is a no-op (canary) —
   anything else means the CHUNKS list drifted from what's committed
   to `theme.json` and the pre-push hook will flag the drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def awc():
    """Load bin/append-wc-overrides.py as a module.

    The script has a hyphen in its filename, so we import it via
    importlib spec. Tests that need to mutate its module-level `ROOT`
    do so directly on the returned module.
    """
    import importlib.util
    from pathlib import Path as _P

    bin_dir = _P(__file__).resolve().parent.parent.parent / "bin"
    spec = importlib.util.spec_from_file_location(
        "append_wc_overrides", bin_dir / "append-wc-overrides.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _theme_json_with_anchor(anchor: str) -> dict:
    """Build a minimal theme.json whose styles.css string ends with the
    archive-polish anchor. This is the shape append-wc-overrides.py
    expects on a theme that hasn't had the chunks applied yet."""
    return {
        "$schema": "https://schemas.wp.org/trunk/theme.json",
        "version": 3,
        "settings": {},
        "styles": {
            "css": f"body{{margin:0;}} {anchor}",
        },
    }


def test_append_for_is_idempotent(awc, tmp_path: Path, monkeypatch):
    """Running `append_for` twice on the same theme yields no change on
    the second run (every chunk reports 'skip')."""
    monkeypatch.setattr(awc, "ROOT", tmp_path)
    theme_dir = tmp_path / "obel"
    theme_dir.mkdir()
    theme_json_path = theme_dir / "theme.json"
    theme_json_path.write_text(
        json.dumps(_theme_json_with_anchor("/* /archive-product polish */")),
        encoding="utf-8",
    )

    first = awc.append_for("obel")
    assert "obel:" in first
    first_bytes = theme_json_path.read_bytes()
    # First run must have appended the chunks.
    assert b"wc-tells" in first_bytes, f"first run didn't splice anything: {first}"

    second = awc.append_for("obel")
    assert "obel:" in second
    second_bytes = theme_json_path.read_bytes()
    assert first_bytes == second_bytes, (
        "append_for is not idempotent — second run mutated theme.json"
    )
    # Every chunk on the second run should report 'skip'.
    assert "+" not in second.split(":", 1)[1], f"second run had non-skip notes: {second}"
    assert "skip" in second


def test_append_for_fails_without_anchor(awc, tmp_path: Path, monkeypatch):
    """Missing anchor must produce FAIL notes and leave the file alone."""
    monkeypatch.setattr(awc, "ROOT", tmp_path)
    theme_dir = tmp_path / "obel"
    theme_dir.mkdir()
    theme_json_path = theme_dir / "theme.json"
    before = json.dumps(_theme_json_with_anchor("/* NOT THE ANCHOR */"))
    theme_json_path.write_text(before, encoding="utf-8")

    status = awc.append_for("obel")
    assert "FAIL" in status, f"expected FAIL when the anchor is absent, got: {status}"
    after = theme_json_path.read_text(encoding="utf-8")
    assert after == before, "append_for mutated theme.json even though the anchor was missing"


def test_real_themes_are_idempotent(awc, monkeypatch):
    """Canary: running `append_for` against every real theme is a no-op.

    If this test fails, the CHUNKS list drifted and CI's
    `bin/check.py append-wc-overrides` drift check will fail too. Flag
    the issue early here with a clear per-theme message.
    """
    monkeypatch.setattr(awc, "ROOT", Path(awc.ROOT))  # preserve real ROOT
    for theme in awc.THEMES:
        theme_json = awc.ROOT / theme / "theme.json"
        if not theme_json.is_file():
            pytest.skip(f"{theme}: theme.json missing in this checkout")
        before = theme_json.read_bytes()
        status = awc.append_for(theme)
        after = theme_json.read_bytes()
        assert before == after, (
            f"{theme}: append-wc-overrides.py mutated theme.json — "
            f"the committed file is out of sync with CHUNKS.\n"
            f"status: {status}\n"
            f"run `python3 bin/append-wc-overrides.py {theme}` and commit."
        )
