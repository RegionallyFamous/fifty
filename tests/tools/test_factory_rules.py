from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = ROOT / "bin"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BIN_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_catalog_covers_design_unblock_categories() -> None:
    rules = _load("factory_rules")
    unblock = _load("design_unblock")

    assert set(unblock.KNOWN_CATEGORIES) <= rules.categories()


def test_catalog_entries_have_actionable_promotion_metadata() -> None:
    rules = _load("factory_rules")

    for category, rule in rules.RULES.items():
        assert rule.category == category
        assert rule.layer in {"spec", "phase", "render", "recipe", "manual-review"}
        assert rule.mode in {"report-only", "hard-fail", "disabled"}
        assert rule.phase
        assert rule.owner
        assert rule.fixture
        if rule.layer == "manual-review":
            assert rule.manual_review_reason


def test_catalog_unknown_falls_back_to_manual_review() -> None:
    rules = _load("factory_rules")

    rule = rules.get_rule("never-seen-before")

    assert rule.category == "unknown"
    assert rule.layer == "manual-review"
