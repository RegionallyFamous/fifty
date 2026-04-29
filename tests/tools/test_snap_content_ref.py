"""Tests for `bin/snap.py`'s `_retarget_content_ref` helper.

On a PR that introduces a brand-new theme, the theme's playground/
content + images only exist on the PR branch — the blueprint's inlined
`raw.githubusercontent.com/.../main/` URLs 404, and the importer dies
with "W&O CSV looked malformed". CI sets `FIFTY_CONTENT_REF` to the
PR head SHA; snap.py rewrites the blueprint at prep time so the PR's
own content sideloads.

These tests lock in the exact substitution behaviour:
    * unset env + unpublished  → no change
    * unset env + pushed branch→ rewrite to the branch
    * env == "main"            → no change (production URL already correct)
    * env == "<sha>"           → every main-branch URL rewrites to the sha
    * pure text replace        → works inside inline PHP `"data"` strings

Without this carve-out, every new-theme PR fails CI on the snap step
until it merges, which defeats the whole point of a gate.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def retarget():
    """Load `_retarget_content_ref` without paying snap.py's
    module-level Playwright import cost.

    snap.py is ~5k LOC and imports Playwright at module scope, which we
    avoid in tests. We pull just the helper text out via importlib's
    spec API and exec a tiny standalone module containing it plus the
    two constants it touches from `_lib`.
    """
    # Easier + robust: exec snap.py with Playwright stubbed.
    fake_playwright = type(sys)("playwright")
    fake_playwright.sync_api = type(sys)("playwright.sync_api")
    fake_playwright.sync_api.sync_playwright = lambda: None
    fake_playwright.sync_api.Error = Exception
    fake_playwright.sync_api.TimeoutError = Exception
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.sync_api", fake_playwright.sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location("_snap_for_test", BIN_DIR / "snap.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec_module so dataclass annotations (resolved via
    # sys.modules[__module__].__dict__) work. Same pattern as
    # tests/tools/test_bin_scripts_smoke.py — see the comment there.
    sys.modules["_snap_for_test"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pytest.skip("snap.py exited at import (missing system dep)")
    return module._retarget_content_ref


def test_noop_when_env_unset(retarget, monkeypatch):
    monkeypatch.delenv("FIFTY_CONTENT_REF", raising=False)
    monkeypatch.setitem(
        retarget.__globals__,
        "_auto_detect_content_ref",
        lambda: (None, "unpublished"),
    )
    payload = "https://raw.githubusercontent.com/RegionallyFamous/fifty/main/x.csv"
    assert retarget(payload) == payload


def test_rewrites_to_pushed_branch_when_env_unset(retarget, monkeypatch):
    monkeypatch.delenv("FIFTY_CONTENT_REF", raising=False)
    monkeypatch.setitem(
        retarget.__globals__,
        "_auto_detect_content_ref",
        lambda: ("agent/scoped-ci-gates", "branch"),
    )
    payload = "https://raw.githubusercontent.com/RegionallyFamous/fifty/main/x.csv"
    assert retarget(payload, _verbose=False).endswith("/agent/scoped-ci-gates/x.csv")


def test_noop_when_env_is_main(retarget, monkeypatch):
    monkeypatch.setenv("FIFTY_CONTENT_REF", "main")
    payload = "https://raw.githubusercontent.com/RegionallyFamous/fifty/main/x.csv"
    assert retarget(payload) == payload


def test_rewrites_to_sha(retarget, monkeypatch):
    monkeypatch.setenv("FIFTY_CONTENT_REF", "deadbee")
    payload = "https://raw.githubusercontent.com/RegionallyFamous/fifty/main/foundry/playground/content/products.csv"
    out = retarget(payload)
    assert "/main/" not in out
    assert "deadbee" in out
    assert out.endswith("foundry/playground/content/products.csv")


def test_rewrites_url_embedded_in_php_data_string(retarget, monkeypatch):
    """PHP `data` strings in the blueprint carry absolute URLs as string
    literals (`define('WO_CONTENT_BASE_URL', '...main/...')`). The
    substitution must reach inside those too — that's why the helper
    operates on the serialized JSON payload rather than the dict."""
    monkeypatch.setenv("FIFTY_CONTENT_REF", "abc123")
    payload = (
        '{"step": "writeFile", "data": "<?php define(\'WO_CONTENT_BASE_URL\', '
        "'https://raw.githubusercontent.com/RegionallyFamous/fifty/main/foundry/playground/'"
        '); ?>"}'
    )
    out = retarget(payload)
    assert "/main/" not in out
    assert "/abc123/" in out


def test_leaves_unrelated_urls_alone(retarget, monkeypatch):
    """Rewrite is anchored on the exact `<org>/<repo>/main/` tuple, so a
    URL that happens to contain the word `main` elsewhere (or points at
    a different repo) is untouched."""
    monkeypatch.setenv("FIFTY_CONTENT_REF", "abc123")
    payload = (
        "https://raw.githubusercontent.com/SomeoneElse/other/main/file.txt "
        "https://demo.regionallyfamous.com/foundry/"
    )
    assert retarget(payload) == payload
