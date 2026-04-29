from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"
sys.path.insert(0, str(BIN_DIR))

from _lib import classify_changed_paths  # noqa: E402


def test_theme_edit_scopes_to_that_theme() -> None:
    scope = classify_changed_paths(["obel/templates/front-page.html"])

    assert scope.themes == ("obel",)
    assert not scope.all_themes_required
    assert scope.reason == "theme changes"


def test_incubating_theme_is_visible_to_changed_scope() -> None:
    scope = classify_changed_paths(["ember/templates/front-page.html"])

    assert "ember" in scope.themes
    assert not scope.all_themes_required


def test_visual_baseline_edit_scopes_to_theme() -> None:
    scope = classify_changed_paths(["tests/visual-baseline/obel/desktop/home.png"])

    assert scope.themes == ("obel",)
    assert not scope.all_themes_required


def test_render_framework_edit_requires_all_themes() -> None:
    scope = classify_changed_paths(["bin/snap.py"])

    assert scope.all_themes_required
    assert "obel" in scope.themes
    assert "bin/snap.py" in scope.framework_paths


def test_unrelated_tooling_is_repo_infra_not_theme_fleet() -> None:
    scope = classify_changed_paths(["bin/lint.py", "tests/tools/test_lint.py"])

    assert scope.themes == ()
    assert not scope.all_themes_required
    assert scope.has_repo_infra_changes
    assert scope.reason == "repo infrastructure changes"


def test_docs_and_mockups_are_docs_only() -> None:
    scope = classify_changed_paths(["docs/index.html", "mockups/mockup-foo.png"])

    assert scope.themes == ()
    assert not scope.all_themes_required
    assert scope.docs_only
    assert scope.reason == "docs/mockups only"
