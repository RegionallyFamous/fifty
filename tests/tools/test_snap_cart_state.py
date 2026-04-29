from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAP_PY = REPO_ROOT / "bin" / "snap.py"


def test_cart_empty_uses_fresh_anonymous_context() -> None:
    src = SNAP_PY.read_text(encoding="utf-8")

    assert 'route.slug == "cart-empty"' in src
    assert "cannot bleed into the empty-state evidence" in src
    assert "ctx = _new_capture_context(vp)" in src
