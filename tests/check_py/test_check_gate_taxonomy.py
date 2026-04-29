from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _load_check_module():
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location("_check_for_gate_taxonomy", BIN_DIR / "check.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_check_for_gate_taxonomy"] = module
    spec.loader.exec_module(module)
    return module


def test_every_check_has_a_gate_taxonomy() -> None:
    mod = _load_check_module()

    names = [name for name, _ in mod._build_results(offline=True)]
    assert names
    for name in names:
        assert mod._gate_for(name) in mod._GATES


def test_cross_theme_checks_are_pairwise_fleet() -> None:
    mod = _load_check_module()

    assert (
        mod._gate_for("check_all_rendered_text_distinct_across_themes") == mod.GATE_PAIRWISE_FLEET
    )
    assert mod._gate_for("check_product_images_unique_across_themes") == mod.GATE_PAIRWISE_FLEET
    assert mod._gate_for("check_hover_state_legibility") == mod.GATE_WORKSTREAM


def test_cross_theme_roots_always_include_current_root(tmp_path: Path, monkeypatch) -> None:
    mod = _load_check_module()
    theme = tmp_path / "incubating-theme"
    theme.mkdir()
    (theme / "theme.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", theme)
    monkeypatch.setattr(mod, "iter_themes", lambda stages=None: iter([Path("/repo/obel")]))

    roots = mod._cross_theme_roots()

    assert theme in roots
