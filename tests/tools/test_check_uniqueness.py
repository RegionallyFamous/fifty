"""Tests for bin/_check_uniqueness.py (Tier 2.1 of pre-100-themes hardening).

The uniqueness cache is the shared primitive for eight cross-theme
`check_*` functions in bin/check.py. Regressions here silently turn
cached data into stale data, so we test the contract directly:

- content-addressed hashing of the input fileset
- cache hit / miss / force-recompute
- cross-theme collision helpers (exact match + value overlap)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def cu(tmp_path, monkeypatch):
    """Import bin/_check_uniqueness.py with CACHE_ROOT redirected to tmp."""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_check_uniqueness_under_test",
        root / "bin" / "_check_uniqueness.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CACHE_ROOT", tmp_path / "fingerprints")
    monkeypatch.delenv(mod.ENV_FORCE, raising=False)
    return mod


# ------------------------- compute_inputs_hash -------------------------


def test_inputs_hash_stable_for_same_paths_and_contents(cu, tmp_path):
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "b.txt").write_text("beta")
    paths = [tmp_path / "a.txt", tmp_path / "b.txt"]
    assert cu.compute_inputs_hash(paths) == cu.compute_inputs_hash(paths)


def test_inputs_hash_changes_when_content_changes(cu, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("one")
    h1 = cu.compute_inputs_hash([p])
    p.write_text("two")
    h2 = cu.compute_inputs_hash([p])
    assert h1 != h2


def test_inputs_hash_changes_when_file_removed(cu, tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha")
    b.write_text("beta")
    h_both = cu.compute_inputs_hash([a, b])
    h_only_a = cu.compute_inputs_hash([a])
    assert h_both != h_only_a


def test_inputs_hash_ignores_list_order(cu, tmp_path):
    """We sort input paths by name before hashing; alphabetised lists
    must produce the same fingerprint regardless of caller order."""
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("y")
    h1 = cu.compute_inputs_hash([tmp_path / "a.txt", tmp_path / "b.txt"])
    h2 = cu.compute_inputs_hash([tmp_path / "b.txt", tmp_path / "a.txt"])
    assert h1 == h2


# ------------------------- load_or_compute -------------------------


def test_load_or_compute_writes_cache_on_miss(cu, tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"payload": "hi"}

    out = cu.load_or_compute("theme1", "mycheck", [tmp_path / "a.txt"], compute)
    assert out == {"payload": "hi"}
    assert calls["n"] == 1
    assert (cu.CACHE_ROOT / "mycheck" / "theme1.json").exists()


def test_load_or_compute_returns_cached_on_hit(cu, tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"payload": "hi"}

    cu.load_or_compute("theme1", "mycheck", [tmp_path / "a.txt"], compute)
    cu.load_or_compute("theme1", "mycheck", [tmp_path / "a.txt"], compute)
    assert calls["n"] == 1, "second call should read from cache"


def test_load_or_compute_recomputes_when_input_changes(cu, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("one")
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"payload": p.read_text()}

    cu.load_or_compute("theme1", "mycheck", [p], compute)
    p.write_text("two")
    out = cu.load_or_compute("theme1", "mycheck", [p], compute)
    assert calls["n"] == 2
    assert out == {"payload": "two"}


def test_load_or_compute_respects_force_env(cu, tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("hello")
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return 42

    cu.load_or_compute("theme1", "mycheck", [tmp_path / "a.txt"], compute)
    monkeypatch.setenv(cu.ENV_FORCE, "1")
    cu.load_or_compute("theme1", "mycheck", [tmp_path / "a.txt"], compute)
    assert calls["n"] == 2


def test_cached_payload_is_json_inspectable(cu, tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    cu.load_or_compute(
        "theme1",
        "mycheck",
        [tmp_path / "a.txt"],
        lambda: {"k": "v"},
    )
    cached = json.loads((cu.CACHE_ROOT / "mycheck" / "theme1.json").read_text())
    assert cached["theme"] == "theme1"
    assert cached["check"] == "mycheck"
    assert cached["data"] == {"k": "v"}
    assert "inputs_hash" in cached
    assert "emitted_at" in cached


# ------------------------- collect_fleet -------------------------


def test_collect_fleet_maps_slug_to_data(cu, tmp_path):
    t1 = tmp_path / "alpha"
    t2 = tmp_path / "beta"
    t1.mkdir()
    t2.mkdir()
    (t1 / "x.txt").write_text("a1")
    (t2 / "x.txt").write_text("b1")

    def inputs(theme):
        return [theme / "x.txt"]

    def fp(theme):
        return {"sig": (theme / "x.txt").read_text()}

    out = cu.collect_fleet([t1, t2], "k", inputs, fp)
    assert out == {"alpha": {"sig": "a1"}, "beta": {"sig": "b1"}}


def test_collect_fleet_accepts_string_paths(cu, tmp_path):
    t1 = tmp_path / "alpha"
    t1.mkdir()
    (t1 / "x.txt").write_text("a1")
    out = cu.collect_fleet(
        [str(t1)],
        "k",
        lambda t: [t / "x.txt"],
        lambda t: "hit",
    )
    assert out == {"alpha": "hit"}


# ------------------------- find_exact_collisions -------------------------


def test_find_exact_collisions_empty_when_all_distinct(cu):
    by_theme = {"a": {"x": "1"}, "b": {"x": "2"}, "c": {"x": "3"}}
    assert cu.find_exact_collisions(by_theme) == []


def test_find_exact_collisions_clusters_identical(cu):
    by_theme = {"a": {"x": "1"}, "b": {"x": "1"}, "c": {"x": "2"}}
    clusters = cu.find_exact_collisions(by_theme)
    assert len(clusters) == 1
    group, data = clusters[0]
    assert group == frozenset({"a", "b"})
    assert data == {"x": "1"}


# ------------------------- find_value_overlaps -------------------------


def test_find_value_overlaps_reports_shared_values(cu):
    by_theme = {
        "aero": {"hero.jpg": "hash-shared", "solo.jpg": "hash-aero"},
        "obel": {"hero.jpg": "hash-shared", "solo.jpg": "hash-obel"},
        "chonk": {"hero.jpg": "hash-chonk"},
    }
    overlaps = cu.find_value_overlaps(by_theme)
    assert len(overlaps) == 1
    digest, owners = overlaps[0]
    assert digest == "hash-shared"
    assert sorted(owners) == [("aero", "hero.jpg"), ("obel", "hero.jpg")]


def test_find_value_overlaps_returns_empty_when_clean(cu):
    by_theme = {
        "a": {"hero.jpg": "h1"},
        "b": {"hero.jpg": "h2"},
    }
    assert cu.find_value_overlaps(by_theme) == []


# ------------------------- clear_cache -------------------------


def test_clear_cache_removes_specific_check(cu, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    cu.load_or_compute("t1", "foo", [tmp_path / "a.txt"], lambda: 1)
    cu.load_or_compute("t1", "bar", [tmp_path / "a.txt"], lambda: 2)
    removed = cu.clear_cache("foo")
    assert removed == 1
    assert not list((cu.CACHE_ROOT / "foo").glob("*.json"))
    assert list((cu.CACHE_ROOT / "bar").glob("*.json"))


def test_clear_cache_removes_all_when_none(cu, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    cu.load_or_compute("t1", "foo", [tmp_path / "a.txt"], lambda: 1)
    cu.load_or_compute("t1", "bar", [tmp_path / "a.txt"], lambda: 2)
    removed = cu.clear_cache()
    assert removed == 2
    assert not list(cu.CACHE_ROOT.rglob("*.json"))
