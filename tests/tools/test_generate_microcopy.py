from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_wc_microcopy_rewrite_handles_escaped_apostrophe_values(tmp_path: Path) -> None:
    gm = _load_module()
    theme = tmp_path / "agitprop"
    theme.mkdir()
    functions = theme / "functions.php"
    functions.write_text(
        """<?php
// === BEGIN wc microcopy ===
static $map = array(
\t'Thank you. Your order has been received.' => 'ORDER RECEIVED. WE\\'RE ON IT.',
);
// === END wc microcopy ===
""",
        encoding="utf-8",
    )

    rewritten = gm._rewrite_wc_microcopy_block(theme, {"name": "Agitprop"}, quiet=True)
    text = functions.read_text(encoding="utf-8")

    assert rewritten == 1
    assert "'Thank you. Your order has been received.' => 'Parcel record" in text
    assert "ORDER RECEIVED" not in text


def test_extract_strings_handles_php_escaped_apostrophes() -> None:
    gm = _load_module()

    strings = gm._extract_strings(
        "<?php esc_html_e( 'GRAB ONE BEFORE THEY\\'RE GONE.', 'agitprop' ); ?>"
    )

    assert "GRAB ONE BEFORE THEY\\'RE GONE." in strings


def test_api_generation_uses_current_anthropic_model(monkeypatch, tmp_path: Path) -> None:
    gm = _load_module()
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text=json.dumps({"Original checkout copy": "Case closed at the register"})
                    )
                ]
            )

    class FakeAnthropic:
        def __init__(self, *, api_key: str):
            assert api_key == "test-key"
            self.messages = FakeMessages()

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        SimpleNamespace(Anthropic=FakeAnthropic),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    theme = tmp_path / "noir"
    theme.mkdir()
    overrides = gm._generate_overrides_with_api(
        theme,
        {"Original checkout copy": "duplicate"},
        {"name": "Noir", "voice": "hard-boiled"},
        quiet=True,
    )

    assert overrides == {"Original checkout copy": "Case closed at the register"}
    assert calls
    assert calls[0]["model"] == "claude-sonnet-4-6"


def test_find_stale_generated_copy_detects_old_fallback_strings(tmp_path: Path) -> None:
    gm = _load_module()
    theme = tmp_path / "noir"
    templates = theme / "templates"
    templates.mkdir(parents=True)
    (templates / "front-page.html").write_text(
        """<!-- wp:paragraph -->
<p>Noir parcel-room copy 977655</p>
<!-- /wp:paragraph -->
<!-- wp:paragraph -->
<p>Real copy that should stay.</p>
<!-- /wp:paragraph -->
""",
        encoding="utf-8",
    )

    stale = gm._find_stale_generated_copy(theme)

    assert stale == {"Noir parcel-room copy 977655": "stale-generated-copy"}
