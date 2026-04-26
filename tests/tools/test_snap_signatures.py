"""Tests for `bin/snap.py`'s Phase 2 signature-stamp skip logic.

Phase 2 adds content-based signatures so a shoot can look at a
`(theme, viewport, route)` cell, ask "did any of my dependencies
actually change?", and -- if not -- copy the baseline PNG forward
without ever booting Playground or Playwright. The signature captures:

  * SHA256 of every file matching the route's manifest entry (plus the
    global-glob list that affects all routes)
  * SHA256 of bin/snap.py + bin/snap_config.py (Playwright / matcher
    semantics change -> reshoot)
  * Pinned @wp-playground/cli version (a CLI bump can shift the WP
    version and with it the rendered markup, so it must re-trigger)

The tests below cover:

  * `compute_route_signature` returns a stable, deterministic, JSON-
    serializable dict keyed on the right files
  * `_signatures_equal` ignores list ordering of `deps` but catches a
    content change, a schema-version bump, and a CLI pin drift
  * `_should_skip_cell` is a strict AND of (baseline PNG exists) +
    (sig file exists) + (sigs equal), plus the `FIFTY_FORCE_RESHOOT=1`
    env kill switch
  * `_materialize_skipped_cell` copies baseline artifacts into
    tmp/snaps/ and writes a valid skip-stub `findings.json` when there
    is no baseline findings file to reuse
  * `_plan_skip_cells` composes all of the above: with a fresh baseline
    every cell is skippable, flipping a single dep file invalidates
    just the routes that map to it
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def snap_mod(tmp_path, monkeypatch):
    """Import bin/snap.py with Playwright stubbed and with all
    filesystem constants (THEMES_DIR, SNAPS_DIR, BASELINE_DIR, etc.)
    pointed at a tmp tree so the test can freely write/delete
    dependency files without touching the real repo."""
    fake_playwright = type(sys)("playwright")
    fake_playwright.sync_api = type(sys)("playwright.sync_api")
    fake_playwright.sync_api.sync_playwright = lambda: None
    fake_playwright.sync_api.Error = Exception
    fake_playwright.sync_api.TimeoutError = Exception
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.sync_api", fake_playwright.sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "_snap_for_sig_test",
        BIN_DIR / "snap.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_snap_for_sig_test"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pytest.skip("snap.py exited at import (missing system dep)")

    # Point filesystem roots at the tmp tree. `theme_dir(theme)` reads
    # REPO_ROOT/<theme>, so we override REPO_ROOT + the derived dirs.
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir()
    (tmp_repo / "tmp" / "snaps").mkdir(parents=True)
    (tmp_repo / "tests" / "visual-baseline").mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_repo)
    monkeypatch.setattr(module, "SNAPS_DIR", tmp_repo / "tmp" / "snaps")
    monkeypatch.setattr(
        module,
        "BASELINE_DIR",
        tmp_repo / "tests" / "visual-baseline",
    )
    # Stable CLI pin so a real package.json lookup doesn't leak in.
    monkeypatch.setattr(
        module,
        "_pinned_playground_cli_spec",
        lambda: "@wp-playground/cli@1.2.3",
    )
    return module


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_theme(snap_mod, theme: str) -> Path:
    """Write a minimal theme tree under the tmp REPO_ROOT with the
    exact files our ROUTE_DEPENDENCIES / ROUTE_GLOBAL_GLOBS touch so
    signatures have something to hash."""
    tdir = snap_mod.REPO_ROOT / theme
    (tdir / "templates").mkdir(parents=True)
    (tdir / "parts").mkdir(parents=True)
    (tdir / "patterns").mkdir(parents=True)
    (tdir / "styles").mkdir(parents=True)
    (tdir / "playground").mkdir(parents=True)

    (tdir / "theme.json").write_text("{}", encoding="utf-8")
    (tdir / "functions.php").write_text("<?php\n", encoding="utf-8")
    (tdir / "parts" / "header.html").write_text("header-v1", encoding="utf-8")
    (tdir / "parts" / "footer.html").write_text("footer-v1", encoding="utf-8")
    (tdir / "styles" / "winter.json").write_text("{}", encoding="utf-8")
    (tdir / "playground" / "blueprint.json").write_text("{}", encoding="utf-8")

    (tdir / "templates" / "front-page.html").write_text(
        "home-v1",
        encoding="utf-8",
    )
    (tdir / "templates" / "single-product.html").write_text(
        "product-v1",
        encoding="utf-8",
    )
    (tdir / "parts" / "product-meta.html").write_text(
        "meta-v1",
        encoding="utf-8",
    )
    return tdir


def _make_baseline(snap_mod, theme: str, vp: str, slug: str, sig: dict) -> None:
    """Write a matching PNG + sig pair under BASELINE_DIR so
    `_should_skip_cell` can find both halves."""
    png = snap_mod._baseline_png_path(theme, vp, slug)
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake-baseline")
    snap_mod._signature_path(theme, vp, slug).write_text(
        json.dumps(sig),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# compute_route_signature
# ---------------------------------------------------------------------------


class TestComputeRouteSignature:
    def test_deterministic_same_inputs_same_output(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        a = snap_mod.compute_route_signature("demo", "home")
        b = snap_mod.compute_route_signature("demo", "home")
        assert a == b

    def test_json_serializable(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        json.dumps(sig)

    def test_deps_sorted_by_path(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        paths = [d["path"] for d in sig["deps"]]
        assert paths == sorted(paths)

    def test_captures_snap_py_and_cli_pin(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        assert sig["snap_py_sha"]
        assert sig["snap_config_sha"]
        assert sig["playground_cli"] == "@wp-playground/cli@1.2.3"

    def test_version_field_present(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        assert sig["version"] == snap_mod._SIG_VERSION

    def test_dep_change_mutates_sig(self, snap_mod):
        tdir = _seed_theme(snap_mod, "demo")
        before = snap_mod.compute_route_signature("demo", "home")
        (tdir / "templates" / "front-page.html").write_text(
            "home-v2",
            encoding="utf-8",
        )
        after = snap_mod.compute_route_signature("demo", "home")
        assert before != after

    def test_global_glob_file_is_tracked(self, snap_mod):
        """Flipping theme.json (a ROUTE_GLOBAL_GLOBS entry) must change
        the signature of every route, not just the ones that explicitly
        name theme.json in ROUTE_DEPENDENCIES (none do today)."""
        tdir = _seed_theme(snap_mod, "demo")
        before = snap_mod.compute_route_signature("demo", "product-simple")
        (tdir / "theme.json").write_text(
            '{"version": 3}',
            encoding="utf-8",
        )
        after = snap_mod.compute_route_signature("demo", "product-simple")
        assert before != after

    def test_unrelated_route_dep_does_not_affect_other_route(self, snap_mod):
        """Editing a file that belongs only to `home`'s manifest must
        leave the `product-simple` signature alone; this is what lets
        --auto-routes narrow the reshoot to a single route."""
        tdir = _seed_theme(snap_mod, "demo")
        before = snap_mod.compute_route_signature("demo", "product-simple")
        (tdir / "templates" / "front-page.html").write_text(
            "home-v2",
            encoding="utf-8",
        )
        after = snap_mod.compute_route_signature("demo", "product-simple")
        assert before == after


# ---------------------------------------------------------------------------
# _signatures_equal
# ---------------------------------------------------------------------------


class TestSignaturesEqual:
    def _make(self, snap_mod, **overrides):
        base = {
            "version": snap_mod._SIG_VERSION,
            "theme": "demo",
            "route": "home",
            "deps": [
                {"path": "theme.json", "sha": "aaa"},
                {"path": "templates/front-page.html", "sha": "bbb"},
            ],
            "snap_py_sha": "sp",
            "snap_config_sha": "sc",
            "playground_cli": "@wp-playground/cli@1.2.3",
        }
        base.update(overrides)
        return base

    def test_identical(self, snap_mod):
        a = self._make(snap_mod)
        b = self._make(snap_mod)
        assert snap_mod._signatures_equal(a, b)

    def test_deps_reordered_still_equal(self, snap_mod):
        a = self._make(snap_mod)
        b = self._make(snap_mod)
        b["deps"] = list(reversed(b["deps"]))
        assert snap_mod._signatures_equal(a, b)

    def test_dep_sha_change_not_equal(self, snap_mod):
        a = self._make(snap_mod)
        b = self._make(snap_mod)
        b["deps"][0]["sha"] = "zzz"
        assert not snap_mod._signatures_equal(a, b)

    def test_new_dep_not_equal(self, snap_mod):
        a = self._make(snap_mod)
        b = self._make(snap_mod)
        b["deps"].append({"path": "new.html", "sha": "ddd"})
        assert not snap_mod._signatures_equal(a, b)

    def test_version_bump_not_equal(self, snap_mod):
        a = self._make(snap_mod)
        b = self._make(snap_mod, version="999")
        assert not snap_mod._signatures_equal(a, b)

    def test_cli_pin_drift_not_equal(self, snap_mod):
        a = self._make(snap_mod)
        b = self._make(snap_mod, playground_cli="@wp-playground/cli@9.9.9")
        assert not snap_mod._signatures_equal(a, b)

    def test_snap_py_sha_change_not_equal(self, snap_mod):
        a = self._make(snap_mod)
        b = self._make(snap_mod, snap_py_sha="different")
        assert not snap_mod._signatures_equal(a, b)


# ---------------------------------------------------------------------------
# _should_skip_cell
# ---------------------------------------------------------------------------


class TestShouldSkipCell:
    def test_baseline_and_sig_match(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        _make_baseline(snap_mod, "demo", "desktop", "home", sig)
        assert snap_mod._should_skip_cell("demo", "desktop", "home", sig)

    def test_missing_baseline_png_means_shoot(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        # Write only the sig, no PNG.
        snap_mod._signature_path("demo", "desktop", "home").parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        snap_mod._signature_path("demo", "desktop", "home").write_text(
            json.dumps(sig),
            encoding="utf-8",
        )
        assert not snap_mod._should_skip_cell("demo", "desktop", "home", sig)

    def test_missing_sig_file_means_shoot(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        # Write only the PNG, no sig file.
        png = snap_mod._baseline_png_path("demo", "desktop", "home")
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b"fake")
        assert not snap_mod._should_skip_cell("demo", "desktop", "home", sig)

    def test_sig_mismatch_means_shoot(self, snap_mod):
        tdir = _seed_theme(snap_mod, "demo")
        stale = snap_mod.compute_route_signature("demo", "home")
        _make_baseline(snap_mod, "demo", "desktop", "home", stale)
        (tdir / "templates" / "front-page.html").write_text(
            "home-v2",
            encoding="utf-8",
        )
        fresh = snap_mod.compute_route_signature("demo", "home")
        assert fresh != stale
        assert not snap_mod._should_skip_cell("demo", "desktop", "home", fresh)

    def test_force_reshoot_env_overrides(self, snap_mod, monkeypatch):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        _make_baseline(snap_mod, "demo", "desktop", "home", sig)
        monkeypatch.setenv("FIFTY_FORCE_RESHOOT", "1")
        assert not snap_mod._should_skip_cell("demo", "desktop", "home", sig)


# ---------------------------------------------------------------------------
# _materialize_skipped_cell
# ---------------------------------------------------------------------------


class TestMaterializeSkippedCell:
    def test_copies_png_and_writes_stub_findings(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        _make_baseline(snap_mod, "demo", "desktop", "home", sig)

        snap_mod._materialize_skipped_cell("demo", "desktop", "home", sig)

        paths = snap_mod._tmp_cell_paths("demo", "desktop", "home")
        assert paths["png"].is_file()
        assert paths["png"].read_bytes().startswith(b"\x89PNG")

        findings = json.loads(paths["findings"].read_text(encoding="utf-8"))
        # Stub fields must exist so the aggregator / check.py doesn't
        # crash when it shapes them into its model.
        assert findings.get("skipped_via_signature") is True
        assert findings.get("findings") == []
        assert findings.get("console") == []
        assert findings.get("page_errors") == []
        assert findings.get("network_failures") == []

        stamped_sig = json.loads(paths["sig"].read_text(encoding="utf-8"))
        assert snap_mod._signatures_equal(stamped_sig, sig)

    def test_prefers_baseline_findings_when_present(self, snap_mod):
        """If a previous `bin/snap.py baseline` run promoted a
        findings.json alongside the PNG, the skip-copy path should
        surface THAT instead of the empty stub -- otherwise we'd lose
        real warnings the baseline captured."""
        _seed_theme(snap_mod, "demo")
        sig = snap_mod.compute_route_signature("demo", "home")
        _make_baseline(snap_mod, "demo", "desktop", "home", sig)
        baseline_findings = snap_mod.BASELINE_DIR / "demo" / "desktop" / "home.findings.json"
        baseline_findings.write_text(
            json.dumps(
                {
                    "findings": [{"severity": "warn", "kind": "carried-over"}],
                    "console": [],
                    "page_errors": [],
                    "network_failures": [],
                }
            ),
            encoding="utf-8",
        )

        snap_mod._materialize_skipped_cell("demo", "desktop", "home", sig)

        paths = snap_mod._tmp_cell_paths("demo", "desktop", "home")
        findings = json.loads(paths["findings"].read_text(encoding="utf-8"))
        assert any(f.get("kind") == "carried-over" for f in findings.get("findings", []))


# ---------------------------------------------------------------------------
# _plan_skip_cells -- end-to-end glue
# ---------------------------------------------------------------------------


class TestPlanSkipCells:
    def _routes(self, snap_mod, slugs):
        return [r for r in snap_mod.ROUTES if r.slug in slugs]

    def _vps(self, snap_mod, names):
        return [v for v in snap_mod.VIEWPORTS if v.name in names]

    def test_all_cells_skippable_when_baselines_match(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        routes = self._routes(snap_mod, {"home", "product-simple"})
        vps = self._vps(snap_mod, {"desktop", "mobile"})
        for r in routes:
            sig = snap_mod.compute_route_signature("demo", r.slug)
            for vp in vps:
                _make_baseline(snap_mod, "demo", vp.name, r.slug, sig)

        skip, sigs = snap_mod._plan_skip_cells(
            "demo",
            routes,
            vps,
            skip_unchanged=True,
        )
        assert len(skip) == len(routes) * len(vps)
        assert len(sigs) == len(routes) * len(vps)

    def test_route_dep_change_invalidates_only_that_route(self, snap_mod):
        tdir = _seed_theme(snap_mod, "demo")
        routes = self._routes(snap_mod, {"home", "product-simple"})
        vps = self._vps(snap_mod, {"desktop", "mobile"})
        for r in routes:
            sig = snap_mod.compute_route_signature("demo", r.slug)
            for vp in vps:
                _make_baseline(snap_mod, "demo", vp.name, r.slug, sig)

        # Touch only `home`'s dep.
        (tdir / "templates" / "front-page.html").write_text(
            "home-v2",
            encoding="utf-8",
        )
        skip, _sigs = snap_mod._plan_skip_cells(
            "demo",
            routes,
            vps,
            skip_unchanged=True,
        )
        # home is invalidated on both viewports, product-simple still skips.
        skipped_slugs = {slug for _, slug in skip}
        assert "home" not in skipped_slugs
        assert "product-simple" in skipped_slugs

    def test_skip_unchanged_false_empties_skip_set(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        routes = self._routes(snap_mod, {"home"})
        vps = self._vps(snap_mod, {"desktop"})
        sig = snap_mod.compute_route_signature("demo", "home")
        for vp in vps:
            _make_baseline(snap_mod, "demo", vp.name, "home", sig)

        skip, sigs = snap_mod._plan_skip_cells(
            "demo",
            routes,
            vps,
            skip_unchanged=False,
        )
        assert skip == set()
        # Signatures are still computed (so they can be stamped on the
        # fresh shoot, so the NEXT run benefits).
        assert len(sigs) == 1

    def test_no_baseline_no_skip(self, snap_mod):
        _seed_theme(snap_mod, "demo")
        routes = self._routes(snap_mod, {"home"})
        vps = self._vps(snap_mod, {"desktop"})
        skip, _sigs = snap_mod._plan_skip_cells(
            "demo",
            routes,
            vps,
            skip_unchanged=True,
        )
        assert skip == set()
