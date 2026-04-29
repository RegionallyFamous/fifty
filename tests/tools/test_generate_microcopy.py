from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "generate_microcopy_under_test", BIN_DIR / "generate-microcopy.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_microcopy_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_generic_fallback_avoids_original_substring(tmp_path: Path) -> None:
    gm = _load_module()
    theme = tmp_path / "midcentury-depot"
    theme.mkdir()

    replacement = gm._generic_replacement(
        "A short statement of intent.",
        theme,
        {"name": "Midcentury Depot"},
    )

    assert "A short statement of intent." not in replacement
    assert "Midcentury Depot" in replacement


def test_wc_microcopy_rewrite_makes_map_theme_specific(tmp_path: Path) -> None:
    gm = _load_module()
    theme = tmp_path / "midcentury-depot"
    theme.mkdir()
    functions = theme / "functions.php"
    functions.write_text(
        """<?php
// === BEGIN wc microcopy ===
static $map = array(
\t'Estimated total' => 'Total',
\t'Proceed to Checkout' => 'Checkout',
);
// === END wc microcopy ===
""",
        encoding="utf-8",
    )

    rewritten = gm._rewrite_wc_microcopy_block(
        theme,
        {"name": "Midcentury Depot"},
        quiet=True,
    )
    text = functions.read_text(encoding="utf-8")

    assert rewritten == 2
    assert "'Estimated total' => 'Register sum" in text
    assert "'Proceed to Checkout' => 'To the register" in text
    assert "=> 'Total'" not in text
