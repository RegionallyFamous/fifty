"""Tests for `bin/snap.py`'s change-scope classifiers.

The snap pipeline computes "which themes (and soon: which routes) need
re-shooting?" by classifying every path in `git diff` into one of:

    * a theme slug              -> that theme is affected
    * the framework allowlist   -> every theme is affected
    * anything else             -> ignored

Phase 5 of the smart-snaps work narrowed the framework allowlist from
"any file under bin/*" to an explicit short list (see
`SNAP_AFFECTING_FRAMEWORK_FILES` / `_PREFIXES` in bin/snap.py). Before
the narrowing, editing an unrelated tooling script like
`bin/audit-concepts.py` triggered a full all-themes re-shoot at ~10
min/theme of runner time; with 100 themes on the horizon that was a
hard ceiling on iteration speed. The nightly drift sweep is the safety
net for the narrower rule — see .github/workflows/nightly-snap-sweep.yml.

These tests lock in the classifier so future edits can't accidentally
re-broaden the allowlist without a visible test diff.

Phase 1 adds `_changed_routes(theme, base)` on top of this same scoper;
tests for that live alongside in test_snap_changed_routes.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def snap_mod():
    """Load bin/snap.py with Playwright stubbed (it's a module-level
    import and we don't want tests to depend on Playwright being
    installed). Same recipe as test_snap_content_ref.py.
    """
    fake_playwright = type(sys)("playwright")
    fake_playwright.sync_api = type(sys)("playwright.sync_api")
    fake_playwright.sync_api.sync_playwright = lambda: None
    fake_playwright.sync_api.Error = Exception
    fake_playwright.sync_api.TimeoutError = Exception
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.sync_api", fake_playwright.sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location("_snap_for_scope_test", BIN_DIR / "snap.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_snap_for_scope_test"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pytest.skip("snap.py exited at import (missing system dep)")
    return module


# ---------------------------------------------------------------------------
# _is_framework_file: the new narrow allowlist
# ---------------------------------------------------------------------------


class TestIsFrameworkFile:
    """The classifier must say YES to exactly the snap-affecting files
    and NO to everything else. Getting the NO side wrong is what kills
    CI cost at 100 themes — any false positive triggers an all-themes
    reshoot.
    """

    def test_snap_engine_is_framework(self, snap_mod):
        assert snap_mod._is_framework_file("bin/snap.py")
        assert snap_mod._is_framework_file("bin/snap_config.py")

    def test_wc_override_rewriter_is_framework(self, snap_mod):
        # append-wc-overrides.py edits every theme.json; a change there
        # can shift hover/button contrast on every theme simultaneously.
        assert snap_mod._is_framework_file("bin/append-wc-overrides.py")

    def test_blueprint_sync_is_framework(self, snap_mod):
        # sync-playground.py inlines shared playground/*.php into every
        # theme's blueprint — WXR import + WC seeding scripts. A change
        # rewrites every blueprint.json.
        assert snap_mod._is_framework_file("bin/sync-playground.py")

    def test_shared_lib_is_framework(self, snap_mod):
        assert snap_mod._is_framework_file("bin/_lib.py")

    def test_playground_cli_pin_is_framework(self, snap_mod):
        # package.json / package-lock.json pin @wp-playground/cli; a
        # version bump changes the WP/WC runtime and self-invalidates
        # the state cache via boot_server's version marker.
        assert snap_mod._is_framework_file("package.json")
        assert snap_mod._is_framework_file("package-lock.json")

    def test_shared_playground_scripts_are_framework(self, snap_mod):
        # playground/*.php at the repo root get inlined into every
        # theme's blueprint by sync-playground.py. The whole directory
        # is framework-wide via the prefix match.
        assert snap_mod._is_framework_file("playground/wo-cart.php")
        assert snap_mod._is_framework_file("playground/content/products.csv")

    # --- the important NO cases: unrelated tooling must NOT invalidate ---

    def test_audit_scripts_are_not_framework(self, snap_mod):
        # The concept-audit pipeline is entirely docs/side-channel; it
        # cannot move a snap pixel. Used to trigger all-themes reshoots
        # under the old "any bin/* is framework" rule.
        assert not snap_mod._is_framework_file("bin/audit-concepts.py")
        assert not snap_mod._is_framework_file("bin/build-concept-meta.py")
        assert not snap_mod._is_framework_file("bin/check-concept-similarity.py")

    def test_gallery_builder_is_not_framework(self, snap_mod):
        # build-snap-gallery.py reads existing PNGs and produces HTML;
        # it doesn't shoot.
        assert not snap_mod._is_framework_file("bin/build-snap-gallery.py")
        assert not snap_mod._is_framework_file("bin/build-redirects.py")

    def test_docs_and_mockups_are_not_framework(self, snap_mod):
        assert not snap_mod._is_framework_file("docs/concepts/index.html")
        assert not snap_mod._is_framework_file("mockups/mockup-agave.png")
        assert not snap_mod._is_framework_file("README.md")
        assert not snap_mod._is_framework_file("AGENTS.md")

    def test_theme_files_are_not_framework(self, snap_mod):
        # Theme-scoped paths are handled by the theme-slug branch of
        # _changed_themes, not the framework branch. The framework
        # classifier must say NO here or a single theme edit would
        # trigger an all-themes reshoot.
        assert not snap_mod._is_framework_file("aero/theme.json")
        assert not snap_mod._is_framework_file("obel/templates/single-product.html")

    def test_baseline_pngs_are_not_framework(self, snap_mod):
        # tests/visual-baseline/<theme>/** is theme-scoped.
        assert not snap_mod._is_framework_file("tests/visual-baseline/aero/desktop/home.png")

    def test_lint_and_tooling_changes_are_not_framework(self, snap_mod):
        # bin/lint.py, bin/check.py (static), bin/paint-mockup.py etc.
        # are all non-visual-capture tooling. False-positives here are
        # exactly the "cosmetic bin/* edit triggers all-themes reshoot"
        # regression Phase 5 was meant to fix.
        assert not snap_mod._is_framework_file("bin/lint.py")
        assert not snap_mod._is_framework_file("bin/check.py")
        assert not snap_mod._is_framework_file("bin/paint-mockup.py")
        assert not snap_mod._is_framework_file("bin/spec-from-prompt.py")


# ---------------------------------------------------------------------------
# _changed_themes: integration with the git-diff driver
# ---------------------------------------------------------------------------
#
# Rather than exercise the live git subprocesses (slow + non-hermetic),
# we monkey-patch subprocess.run to return a synthesised diff and verify
# the classifier consumes it correctly. This is the same trick
# test_snap_content_ref.py uses for its env-var path, applied one layer
# deeper.


class _FakeRun:
    """Callable replacement for subprocess.run that returns a canned
    stdout for git-diff probes.

    snap._changed_themes calls subprocess.run three times:
      1. `git diff --name-only HEAD`
      2. `git ls-files --others --exclude-standard`
      3. `git diff --name-only {base}...HEAD`  (only if base is truthy)

    We return the same canned stdout for all three so the test can
    reason about "these paths were touched" regardless of which git
    command the production code happens to use internally.
    """

    def __init__(self, lines: list[str]):
        self.lines = lines

    def __call__(self, *args, **kwargs):
        class _R:
            returncode = 0
            stdout = "\n".join(self.lines)

        return _R()


def test_changed_themes_picks_up_theme_dir_edits(snap_mod, monkeypatch):
    monkeypatch.setattr(
        snap_mod,
        "discover_themes",
        lambda **_kw: ["aero", "obel", "selvedge"],
    )
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun(["aero/templates/single-product.html"]),
    )
    assert snap_mod._changed_themes("origin/main") == ["aero"]


def test_changed_themes_sees_incubating_themes(snap_mod, monkeypatch):
    """`_changed_themes` must include incubating themes in its `known`
    set, not just shipping ones.

    Rationale: a brand-new theme cloned via `bin/clone.py` lands at
    `readiness.stage = "incubating"`. `discover_themes()` (stages=None)
    excludes incubating themes by design so `--all` fan-outs don't
    rope them in. But every per-PR gate (quick-visual, vision-review)
    uses `_changed_themes()` to populate its matrix — and if that
    function filters through the shipping-only set, a PR that adds
    a new incubating theme ends up with an empty matrix → review
    jobs skip → `vision-reviewed` label never auto-applies →
    check.yml's vision-review-gate blocks the PR forever (chicken-
    and-egg). This test locks in the `stages=("shipping",
    "incubating")` override in `_changed_themes`.
    """

    def _discover(stages=None):
        if stages and "incubating" in stages:
            return ["aero", "obel", "selvedge", "apiary"]
        return ["aero", "obel", "selvedge"]

    monkeypatch.setattr(snap_mod, "discover_themes", _discover)
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun(["apiary/templates/single-product.html"]),
    )
    assert snap_mod._changed_themes("origin/main") == ["apiary"]


def test_changed_themes_picks_up_baseline_dir_edits(snap_mod, monkeypatch):
    # tests/visual-baseline/<theme>/** counts as an edit to that theme
    # because it's the canonical "expected pixels" that snap diff
    # compares against.
    monkeypatch.setattr(
        snap_mod,
        "discover_themes",
        lambda **_kw: ["aero", "obel"],
    )
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun(["tests/visual-baseline/obel/desktop/home.png"]),
    )
    assert snap_mod._changed_themes("origin/main") == ["obel"]


def test_changed_themes_falls_back_to_all_on_framework_file(snap_mod, monkeypatch):
    monkeypatch.setattr(
        snap_mod,
        "discover_themes",
        lambda **_kw: ["aero", "obel"],
    )
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun(["bin/snap.py"]),
    )
    # None is the "shoot everything" sentinel.
    assert snap_mod._changed_themes("origin/main") is None


def test_changed_themes_ignores_non_framework_bin_edits(snap_mod, monkeypatch):
    # Before Phase 5 this returned None (all themes). After Phase 5 it
    # returns an empty list -- editing a concept-audit script doesn't
    # invalidate any snap.
    monkeypatch.setattr(
        snap_mod,
        "discover_themes",
        lambda **_kw: ["aero", "obel"],
    )
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun(["bin/audit-concepts.py", "docs/concepts/AUDIT.md"]),
    )
    assert snap_mod._changed_themes("origin/main") == []


def test_changed_themes_mixed_theme_plus_nonframework_bin(snap_mod, monkeypatch):
    # The theme edit still wins; the unrelated bin/* edit is a no-op.
    monkeypatch.setattr(
        snap_mod,
        "discover_themes",
        lambda **_kw: ["aero", "obel"],
    )
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun(
            [
                "aero/theme.json",
                "bin/build-snap-gallery.py",  # not framework
            ]
        ),
    )
    assert snap_mod._changed_themes("origin/main") == ["aero"]


def test_changed_themes_empty_diff(snap_mod, monkeypatch):
    monkeypatch.setattr(
        snap_mod,
        "discover_themes",
        lambda **_kw: ["aero", "obel"],
    )
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun([]),
    )
    assert snap_mod._changed_themes("origin/main") == []


def test_cmd_report_default_theme_discovery_sees_incubating(
    snap_mod, monkeypatch, tmp_path
):
    """`cmd_report` with no `--theme`/`--all`/`--changed` must include
    incubating themes when enumerating what was last shot.

    Sibling to `test_changed_themes_sees_incubating_themes`: the same
    chicken-and-egg pattern hit a second surface. The default
    ("report whatever is in SNAPS_DIR") branch filters
    ``p.name in discover_themes()`` — and since
    ``discover_themes()`` with ``stages=None`` excludes incubating
    themes, a PR that only touched an incubating theme shoots the
    theme, writes `tmp/snaps/<slug>/**/findings.json`, then gets
    "No snaps to report on." from `report` because the filter drops
    the only theme on disk. The workflow step's `if: hashFiles(...)`
    guard is passed (findings DO exist), so we reach report and
    crash. The fix mirrors `_changed_themes`: pass
    ``stages=("shipping", "incubating")`` in the PR-workflow path.
    """
    # Build a fake SNAPS_DIR tree with one incubating theme that's been
    # shot, and make discover_themes() lie about shipping vs shipping+incubating
    # so the filter expression is the thing under test.
    fake_snaps = tmp_path / "tmp" / "snaps"
    fake_snaps.mkdir(parents=True)
    (fake_snaps / "apiary").mkdir()  # shot incubating theme

    monkeypatch.setattr(snap_mod, "SNAPS_DIR", fake_snaps)

    def _discover(stages=None):
        if stages and "incubating" in stages:
            return ["aero", "obel", "apiary"]
        return ["aero", "obel"]

    monkeypatch.setattr(snap_mod, "discover_themes", _discover)
    # Also stub the downstream findings loader so cmd_report early-exits
    # past the empty-theme crash we're protecting against and can't
    # reach the parts of the function that need a real findings.json.
    monkeypatch.setattr(snap_mod, "_gather_findings", lambda _themes: [])
    monkeypatch.setattr(snap_mod, "_cross_theme_parity", lambda _p: [])

    class _Args:
        theme = None
        all = False
        changed = False
        format = "json"
        strict = False

    # Before the fix this raised SystemExit("No snaps to report on.").
    # After the fix it exits cleanly with 0 (nothing to report AFTER the
    # filter, but not the false "never ran" exit).
    rc = snap_mod.cmd_report(_Args())
    assert rc == 0


def test_changed_themes_playground_dir_is_framework(snap_mod, monkeypatch):
    # playground/*.php at the REPO ROOT is shared across every theme's
    # blueprint. Theme-specific `<theme>/playground/**` edits are
    # already handled by the theme-slug branch.
    monkeypatch.setattr(
        snap_mod,
        "discover_themes",
        lambda **_kw: ["aero", "obel"],
    )
    monkeypatch.setattr(
        snap_mod.subprocess,
        "run",
        _FakeRun(["playground/wo-cart.php"]),
    )
    assert snap_mod._changed_themes("origin/main") is None
