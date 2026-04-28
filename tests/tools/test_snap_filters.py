from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture(scope="module")
def snap_module():
    fake_playwright = type(sys)("playwright")
    fake_playwright.sync_api = type(sys)("playwright.sync_api")
    fake_playwright.sync_api.sync_playwright = lambda: None
    fake_playwright.sync_api.Error = Exception
    fake_playwright.sync_api.TimeoutError = Exception
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.sync_api", fake_playwright.sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location("_snap_filters_for_test", BIN_DIR / "snap.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_snap_filters_for_test"] = module
    spec.loader.exec_module(module)
    return module


def test_filter_routes_accepts_comma_separated_values(snap_module):
    picked = snap_module.filter_routes(["shop,category"])
    assert [route.slug for route in picked] == ["shop", "category"]


def test_filter_viewports_accepts_comma_separated_values(snap_module):
    picked = snap_module.filter_viewports(["mobile,desktop"])
    assert [viewport.name for viewport in picked] == ["mobile", "desktop"]


def test_filter_routes_rejects_unknown_names(snap_module):
    with pytest.raises(SystemExit) as exc:
        snap_module.filter_routes(["shop,nope"])
    assert "Unknown route(s): nope" in str(exc.value)
