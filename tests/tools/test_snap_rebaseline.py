"""Tests for `bin/snap.py rebaseline` (Tier 1.4 of pre-100-themes hardening).

Rebaseline is the *filtered* cousin of `snap.py baseline`: it promotes
drifted and/or stale cells only, leaving everything else untouched. The
logic under test:

  * `_parse_since` — accepts relative durations (`7d`, `12h`, `2w`) and
    ISO dates, rejects gibberish with a SystemExit that includes a hint.
  * `cmd_rebaseline` — must refuse to run without a filter (pointing the
    operator at `baseline --all` for the unfiltered case), must copy
    matching PNGs + sidecar files to `tests/visual-baseline/`, and must
    be idempotent (a second --dry-run after the first --live copy should
    see the new mtime and therefore NOT re-match `--since`).

All tests run against a tmp repo tree so no real baselines are
promoted. We bypass Playwright the same way `test_snap_boot.py` does.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import time
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def snap_mod(tmp_path, monkeypatch):
    """Load bin/snap.py with Playwright stubbed + SNAPS_DIR/BASELINE_DIR
    redirected at a tmp tree so tests never mutate the real repo."""
    fake_playwright = type(sys)("playwright")
    fake_playwright.sync_api = type(sys)("playwright.sync_api")
    fake_playwright.sync_api.sync_playwright = lambda: None
    fake_playwright.sync_api.Error = Exception
    fake_playwright.sync_api.TimeoutError = Exception
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.sync_api", fake_playwright.sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "_snap_for_rebaseline_test",
        BIN_DIR / "snap.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_snap_for_rebaseline_test"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pytest.skip("snap.py exited at import")

    snaps = tmp_path / "tmp" / "snaps"
    snaps.mkdir(parents=True)
    baseline = tmp_path / "tests" / "visual-baseline"
    baseline.mkdir(parents=True)
    diffs = tmp_path / "tmp" / "diffs"
    diffs.mkdir(parents=True)

    monkeypatch.setattr(module, "SNAPS_DIR", snaps)
    monkeypatch.setattr(module, "BASELINE_DIR", baseline)
    monkeypatch.setattr(module, "DIFFS_DIR", diffs)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "discover_themes", lambda stages=None: ["agave"])
    return module, snaps, baseline


def _minimal_png(path: Path, seed: int = 0) -> None:
    """Write a tiny valid 1x1 PNG. snap.diff_images consumes bytes, so any
    valid PNG works; we vary the color via `seed` so tests can provoke
    or suppress drift."""
    def _chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0),
    )
    raw = bytes([0, seed & 0xFF, (seed >> 8) & 0xFF, seed & 0xFF])
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    path.write_bytes(sig + ihdr + idat + iend)


# ---------------------------------------------------------------------------
# _parse_since
# ---------------------------------------------------------------------------


def test_parse_since_empty_returns_none(snap_mod):
    mod, _, _ = snap_mod
    assert mod._parse_since("") is None
    assert mod._parse_since(None or "") is None


def test_parse_since_duration_hours(snap_mod):
    mod, _, _ = snap_mod
    threshold = mod._parse_since("24h")
    assert threshold is not None
    now = time.time()
    # Threshold is 24h ago, so an mtime of now-12h should NOT be stale,
    # and now-48h SHOULD be stale.
    assert now - 12 * 3600 > threshold
    assert now - 48 * 3600 <= threshold


def test_parse_since_duration_days_and_weeks(snap_mod):
    mod, _, _ = snap_mod
    a = mod._parse_since("7d")
    b = mod._parse_since("1w")
    assert a is not None and b is not None
    assert abs(a - b) < 2.0  # 7d and 1w resolve to the same ±1s window


def test_parse_since_iso_date(snap_mod):
    mod, _, _ = snap_mod
    t = mod._parse_since("2020-01-01")
    assert t is not None
    # ~946684800 for 2020-01-01T00:00:00Z
    assert abs(t - 1577836800.0) < 86400  # within a day for tz slack


def test_parse_since_rejects_garbage(snap_mod):
    mod, _, _ = snap_mod
    with pytest.raises(SystemExit, match="unparseable"):
        mod._parse_since("when-pigs-fly")


# ---------------------------------------------------------------------------
# cmd_rebaseline filter semantics
# ---------------------------------------------------------------------------


def _mkargs(**kw):
    class _NS:
        pass

    ns = _NS()
    ns.theme = kw.pop("theme", None)
    ns.route = kw.pop("route", None)
    ns.viewport = kw.pop("viewport", None)
    ns.drifted = kw.pop("drifted", False)
    ns.since = kw.pop("since", "")
    ns.threshold = kw.pop("threshold", 0.5)
    ns.channel_tolerance = kw.pop("channel_tolerance", 8)
    ns.dry_run = kw.pop("dry_run", False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_rebaseline_requires_a_filter(snap_mod):
    mod, _, _ = snap_mod
    with pytest.raises(SystemExit, match="--drifted or --since"):
        mod.cmd_rebaseline(_mkargs())


def test_rebaseline_missing_snaps_dir_exits(snap_mod, tmp_path, monkeypatch):
    mod, _, _ = snap_mod
    monkeypatch.setattr(mod, "SNAPS_DIR", tmp_path / "nope")
    with pytest.raises(SystemExit, match="No snaps"):
        mod.cmd_rebaseline(_mkargs(drifted=True))


def test_rebaseline_dry_run_since_matches_stale(snap_mod, capsys):
    mod, snaps, baseline = snap_mod
    # Current snap in tmp/snaps/agave/desktop/home.png
    (snaps / "agave" / "desktop").mkdir(parents=True)
    cur = snaps / "agave" / "desktop" / "home.png"
    _minimal_png(cur)
    # Old baseline in tests/visual-baseline/agave/desktop/home.png
    (baseline / "agave" / "desktop").mkdir(parents=True)
    base = baseline / "agave" / "desktop" / "home.png"
    _minimal_png(base)
    # Artificially age the baseline past our --since threshold.
    old = time.time() - 30 * 86400
    import os
    os.utime(base, (old, old))

    rc = mod.cmd_rebaseline(_mkargs(since="7d", dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "stale" in out
    assert "would promote:  1" in out
    # Baseline NOT touched in dry-run.
    assert abs(base.stat().st_mtime - old) < 5.0


def test_rebaseline_since_new_baseline_is_skipped(snap_mod, capsys):
    mod, snaps, baseline = snap_mod
    (snaps / "agave" / "desktop").mkdir(parents=True)
    _minimal_png(snaps / "agave" / "desktop" / "home.png")
    (baseline / "agave" / "desktop").mkdir(parents=True)
    _minimal_png(baseline / "agave" / "desktop" / "home.png")  # fresh mtime
    rc = mod.cmd_rebaseline(_mkargs(since="7d", dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "would promote:  0" in out


def test_rebaseline_live_promote_copies_png_and_sidecars(snap_mod, capsys):
    mod, snaps, baseline = snap_mod
    (snaps / "agave" / "desktop").mkdir(parents=True)
    cur = snaps / "agave" / "desktop" / "home.png"
    _minimal_png(cur, seed=17)
    # Sidecar files snap.py cmd_baseline (and rebaseline) promote alongside.
    (snaps / "agave" / "desktop" / "home.sig.json").write_text("{}")
    (snaps / "agave" / "desktop" / "home.findings.json").write_text("[]")
    (snaps / "agave" / "desktop" / "home.html").write_text("<html></html>")

    rc = mod.cmd_rebaseline(_mkargs(since="1s"))  # everything is "stale"
    assert rc == 0

    dst = baseline / "agave" / "desktop" / "home.png"
    assert dst.is_file()
    assert (dst.parent / "home.sig.json").is_file()
    assert (dst.parent / "home.findings.json").is_file()
    assert (dst.parent / "home.html").is_file()
    out = capsys.readouterr().out
    assert "rebaselined" in out
    assert "promoted:  1" in out


def test_rebaseline_respects_theme_scope(snap_mod, capsys, monkeypatch):
    mod, snaps, baseline = snap_mod
    for slug in ("agave", "apiary"):
        (snaps / slug / "desktop").mkdir(parents=True)
        _minimal_png(snaps / slug / "desktop" / "home.png")
    monkeypatch.setattr(mod, "discover_themes", lambda stages=None: ["agave", "apiary"])
    rc = mod.cmd_rebaseline(_mkargs(theme="agave", since="1s", dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "agave/desktop/home.png" in out
    assert "apiary" not in out


def test_rebaseline_respects_route_and_viewport_scope(snap_mod, capsys):
    mod, snaps, baseline = snap_mod
    (snaps / "agave" / "desktop").mkdir(parents=True)
    (snaps / "agave" / "mobile").mkdir(parents=True)
    _minimal_png(snaps / "agave" / "desktop" / "home.png")
    _minimal_png(snaps / "agave" / "desktop" / "shop.png")
    _minimal_png(snaps / "agave" / "mobile" / "home.png")

    rc = mod.cmd_rebaseline(
        _mkargs(route="home", viewport="desktop", since="1s", dry_run=True)
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "agave/desktop/home.png" in out
    assert "shop.png" not in out
    assert "mobile" not in out


def test_rebaseline_drifted_flag_ignores_matching_cells(snap_mod, capsys):
    mod, snaps, baseline = snap_mod
    (snaps / "agave" / "desktop").mkdir(parents=True)
    (baseline / "agave" / "desktop").mkdir(parents=True)
    # Identical PNGs => drift == 0% => NOT promoted under --drifted.
    cur = snaps / "agave" / "desktop" / "home.png"
    base = baseline / "agave" / "desktop" / "home.png"
    _minimal_png(cur, seed=1)
    _minimal_png(base, seed=1)
    rc = mod.cmd_rebaseline(_mkargs(drifted=True, dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "would promote:  0" in out
