from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "apply_microcopy_under_test", BIN_DIR / "apply-microcopy-overrides.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["apply_microcopy_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_apply_overrides_escapes_apostrophes_in_php_i18n(tmp_path: Path) -> None:
    amo = _load_module()
    theme = tmp_path / "noir"
    patterns = theme / "patterns"
    patterns.mkdir(parents=True)
    pattern = patterns / "value-props.php"
    pattern.write_text(
        "<?php esc_html_e( 'Old copy', 'noir' ); ?>\n<p>Old copy</p>\n",
        encoding="utf-8",
    )

    files, subs = amo.apply_overrides(
        theme,
        {"Old copy": "The clock's still running"},
        quiet=True,
    )

    text = pattern.read_text(encoding="utf-8")
    assert (files, subs) == (1, 2)
    assert "esc_html_e( 'The clock\\'s still running', 'noir' );" in text
    assert "<p>The clock's still running</p>" in text
