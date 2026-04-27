"""Tests for `bin/_readiness.py` + the three discovery sites (Tier 1.3).

The readiness manifest drives whether a theme is visible to:

  * `_lib.iter_themes`           -- used by most bin/ scripts
  * `snap.discover_themes`       -- visual pipeline
  * `append-wc-overrides.discover_themes` -- WC CSS chain

Contract under test:

  * A theme with no manifest on disk is treated as stage="shipping"
    (backward compat).
  * A theme with stage="incubating" drops out of the default filter.
  * A theme with stage="retired" drops out of the default filter.
  * `stages=()` (empty) yields every theme regardless of stage -- used
    by the status dashboard that needs to see the whole fleet.
  * `stages=("incubating",)` opts IN to WIP themes (design.py use case).
  * A malformed JSON body or unknown stage value falls back to
    stage="shipping" in discovery code (so one bad manifest can't
    hide the fleet) but `validate_payload` flags it for check.py to
    report.
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
def readiness_mod():
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "_readiness_under_test", BIN_DIR / "_readiness.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_readiness_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_repo(tmp_path):
    """Build a tmp repo with four themes at varying stages and assert
    they all have the minimum files the discovery layer looks for
    (theme.json + playground/blueprint.json)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bin").mkdir()
    specs = {
        "obel": {"stage": "shipping", "summary": "shipping 1", "owner": "nick"},
        "chonk": {"stage": "shipping", "summary": "shipping 2", "owner": "nick"},
        # Incubating theme -- default discovery should hide it.
        "agave": {
            "stage": "incubating",
            "summary": "WIP specimen grid",
            "owner": "nick",
        },
        # Retired theme -- default discovery should hide it too.
        "bygone": {
            "stage": "retired",
            "summary": "deprecated, kept for redirect map",
            "owner": "nick",
        },
        # Theme with NO manifest -- must default to shipping.
        "legacy": None,
    }
    for slug, payload in specs.items():
        tdir = repo / slug
        tdir.mkdir()
        (tdir / "theme.json").write_text("{}", encoding="utf-8")
        (tdir / "playground").mkdir()
        (tdir / "playground" / "blueprint.json").write_text("{}", encoding="utf-8")
        if payload is not None:
            (tdir / "readiness.json").write_text(json.dumps(payload), encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# _readiness module
# ---------------------------------------------------------------------------


def test_load_readiness_missing_defaults_to_shipping(readiness_mod, tmp_path):
    r = readiness_mod.load_readiness(tmp_path)
    assert r.stage == "shipping"
    assert r.exists is False
    assert r.source is None


def test_load_readiness_valid_incubating(readiness_mod, tmp_path):
    (tmp_path / "readiness.json").write_text(
        json.dumps({"stage": "incubating", "owner": "nick"}),
        encoding="utf-8",
    )
    r = readiness_mod.load_readiness(tmp_path)
    assert r.stage == "incubating"
    assert r.owner == "nick"
    assert r.exists is True


def test_load_readiness_malformed_json_is_default(readiness_mod, tmp_path):
    (tmp_path / "readiness.json").write_text("{not json", encoding="utf-8")
    r = readiness_mod.load_readiness(tmp_path)
    assert r.stage == "shipping"
    assert r.exists is True  # file was there, just bad contents


def test_load_readiness_unknown_stage_falls_back_to_shipping(readiness_mod, tmp_path):
    (tmp_path / "readiness.json").write_text(json.dumps({"stage": "prototype"}), encoding="utf-8")
    r = readiness_mod.load_readiness(tmp_path)
    assert r.stage == "shipping"


def test_load_readiness_non_object_root(readiness_mod, tmp_path):
    (tmp_path / "readiness.json").write_text("[]", encoding="utf-8")
    r = readiness_mod.load_readiness(tmp_path)
    assert r.stage == "shipping"


def test_is_visible_default_hides_incubating(readiness_mod, tmp_path):
    (tmp_path / "readiness.json").write_text(json.dumps({"stage": "incubating"}), encoding="utf-8")
    assert not readiness_mod.is_visible(tmp_path)


def test_is_visible_explicit_includes_incubating(readiness_mod, tmp_path):
    (tmp_path / "readiness.json").write_text(json.dumps({"stage": "incubating"}), encoding="utf-8")
    assert readiness_mod.is_visible(tmp_path, stages=("shipping", "incubating"))


def test_is_visible_retired_always_hidden_by_default(readiness_mod, tmp_path):
    (tmp_path / "readiness.json").write_text(json.dumps({"stage": "retired"}), encoding="utf-8")
    assert not readiness_mod.is_visible(tmp_path)


def test_validate_payload_requires_stage(readiness_mod):
    assert readiness_mod.validate_payload({"summary": "x"}) == [
        "`stage` is required and must be a string"
    ]


def test_validate_payload_rejects_unknown_stage(readiness_mod):
    problems = readiness_mod.validate_payload({"stage": "prototype"})
    assert any("must be one of" in p for p in problems)


def test_validate_payload_rejects_non_string_summary(readiness_mod):
    problems = readiness_mod.validate_payload({"stage": "shipping", "summary": 42})
    assert any("summary" in p for p in problems)


def test_validate_payload_accepts_minimal_shipping(readiness_mod):
    assert readiness_mod.validate_payload({"stage": "shipping"}) == []


def test_validate_payload_accepts_all_three_stages(readiness_mod):
    for stage in ("shipping", "incubating", "retired"):
        assert readiness_mod.validate_payload({"stage": stage}) == []


def test_validate_payload_rejects_array_root(readiness_mod):
    assert readiness_mod.validate_payload([]) == ["readiness.json root must be a JSON object"]


# ---------------------------------------------------------------------------
# _lib.iter_themes
# ---------------------------------------------------------------------------


def _load_lib_with_root(tmp_repo: Path):
    """Import _lib.py with MONOREPO_ROOT pointed at our fake repo."""
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location("_lib_under_test_readiness", BIN_DIR / "_lib.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lib_under_test_readiness"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_iter_themes_default_hides_incubating_and_retired(readiness_mod, fake_repo):
    lib = _load_lib_with_root(fake_repo)
    slugs = sorted(t.name for t in lib.iter_themes(fake_repo))
    assert "agave" not in slugs  # incubating
    assert "bygone" not in slugs  # retired
    assert "obel" in slugs
    assert "chonk" in slugs
    assert "legacy" in slugs  # no manifest => default shipping


def test_iter_themes_explicit_stages_shows_incubating(readiness_mod, fake_repo):
    lib = _load_lib_with_root(fake_repo)
    slugs = sorted(t.name for t in lib.iter_themes(fake_repo, stages=("shipping", "incubating")))
    assert "agave" in slugs
    assert "obel" in slugs
    assert "bygone" not in slugs  # still excluded


def test_iter_themes_empty_stages_yields_all(readiness_mod, fake_repo):
    lib = _load_lib_with_root(fake_repo)
    slugs = sorted(t.name for t in lib.iter_themes(fake_repo, stages=()))
    assert {"agave", "bygone", "chonk", "legacy", "obel"} == set(slugs)


# ---------------------------------------------------------------------------
# snap.discover_themes
# ---------------------------------------------------------------------------


def _load_snap_with_root(tmp_repo: Path, monkeypatch):
    # Stub playwright as elsewhere in the test suite. The sync_api
    # submodule is assigned to the fake module; mypy flags that as
    # "no attribute" on a bare ModuleType, so pre-populate sys.modules
    # with the submodule BEFORE attaching it to the parent so the
    # attribute lookup at import time resolves through sys.modules.
    fake = type(sys)("playwright")
    fake_sync_api = type(sys)("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: None  # type: ignore[attr-defined]
    fake_sync_api.Error = Exception  # type: ignore[attr-defined]
    fake_sync_api.TimeoutError = Exception  # type: ignore[attr-defined]
    sys.modules.setdefault("playwright", fake)
    sys.modules.setdefault("playwright.sync_api", fake_sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location("_snap_for_readiness", BIN_DIR / "snap.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_snap_for_readiness"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_repo)
    # THEME_ORDER is a list import from snap_config. Make it neutral so
    # the sorted "extras" path is exercised for our fake themes.
    monkeypatch.setattr(mod, "THEME_ORDER", [])
    return mod


def test_snap_discover_themes_default_excludes_incubating(readiness_mod, fake_repo, monkeypatch):
    snap = _load_snap_with_root(fake_repo, monkeypatch)
    slugs = snap.discover_themes()
    assert "agave" not in slugs
    assert "bygone" not in slugs
    assert "obel" in slugs
    assert "legacy" in slugs


def test_snap_discover_themes_opt_in_incubating(readiness_mod, fake_repo, monkeypatch):
    snap = _load_snap_with_root(fake_repo, monkeypatch)
    slugs = snap.discover_themes(stages=("shipping", "incubating"))
    assert "agave" in slugs
    assert "bygone" not in slugs


def test_snap_discover_themes_empty_yields_all(readiness_mod, fake_repo, monkeypatch):
    snap = _load_snap_with_root(fake_repo, monkeypatch)
    slugs = snap.discover_themes(stages=())
    assert {"agave", "bygone", "chonk", "legacy", "obel"} == set(slugs)


# ---------------------------------------------------------------------------
# append-wc-overrides.discover_themes
# ---------------------------------------------------------------------------


def _load_wc_overrides_with_root(tmp_repo: Path, monkeypatch):
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "_wc_overrides_for_readiness", BIN_DIR / "append-wc-overrides.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_wc_overrides_for_readiness"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_repo)
    return mod


def test_wc_overrides_discover_default_hides_incubating(readiness_mod, fake_repo, monkeypatch):
    mod = _load_wc_overrides_with_root(fake_repo, monkeypatch)
    slugs = mod.discover_themes()
    assert "agave" not in slugs
    assert "bygone" not in slugs
    assert "obel" in slugs


def test_wc_overrides_discover_opt_in_incubating(readiness_mod, fake_repo, monkeypatch):
    mod = _load_wc_overrides_with_root(fake_repo, monkeypatch)
    slugs = mod.discover_themes(stages=("shipping", "incubating"))
    assert "agave" in slugs


# ---------------------------------------------------------------------------
# Actual repo state: backfill must have made existing themes shipping
# ---------------------------------------------------------------------------


def test_existing_themes_have_readiness_manifests(readiness_mod):
    """Every theme in the real repo must have a readiness.json after
    the backfill. This test runs against the live REPO_ROOT so the
    CI catches a theme being added without a manifest."""
    have = sorted(
        p.parent
        for p in REPO_ROOT.glob("*/theme.json")
        if (p.parent / "playground" / "blueprint.json").exists()
    )
    missing = [t.name for t in have if not (t / "readiness.json").is_file()]
    assert missing == [], f"Themes missing readiness.json after backfill: {missing}"
    for theme_dir in have:
        r = readiness_mod.load_readiness(theme_dir)
        assert r.stage in {"shipping", "incubating", "retired"}
