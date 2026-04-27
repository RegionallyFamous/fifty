"""Tests for bin/build-theme-status.py (Tier 2.2 of pre-100-themes hardening)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture
def bts():
    """Import bin/build-theme-status.py as a module under an alias."""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "build_theme_status_under_test",
        root / "bin" / "build-theme-status.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------- CellStatus + helpers ----------------


def test_stage_cell_shipping_green(bts):
    c = bts._stage_cell("shipping", source_exists=True)
    assert c.tone == "green"
    assert c.label == "shipping"
    assert c.detail == "shipping"


def test_stage_cell_incubating_yellow(bts):
    c = bts._stage_cell("incubating", source_exists=True)
    assert c.tone == "yellow"
    assert c.label == "incubating"


def test_stage_cell_retired_grey(bts):
    c = bts._stage_cell("retired", source_exists=True)
    assert c.tone == "grey"


def test_stage_cell_missing_manifest_shows_default_marker(bts):
    c = bts._stage_cell("shipping", source_exists=False)
    assert "default" in c.detail
    assert "no readiness.json" in c.detail


def test_boot_cell_missing_returns_grey(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "TMP_DIR", tmp_path)
    c = bts._boot_cell("aero")
    assert c.tone == "grey"
    assert c.label == "unknown"


def test_boot_cell_ok_is_green(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "TMP_DIR", tmp_path)
    (tmp_path / "aero-boot.json").write_text(
        '{"theme":"aero","elapsed_s":12.3,"ok":true,"reasons":[]}'
    )
    c = bts._boot_cell("aero")
    assert c.tone == "green"
    assert c.label == "boots"
    assert "12.3s" in c.detail


def test_boot_cell_fail_surfaces_reason(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "TMP_DIR", tmp_path)
    (tmp_path / "obel-boot.json").write_text(
        '{"theme":"obel","ok":false,"reasons":["/cart: HTTP 500"]}'
    )
    c = bts._boot_cell("obel")
    assert c.tone == "red"
    assert "/cart" in c.detail


def test_baseline_age_cell_missing_returns_grey(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "BASELINE_ROOT", tmp_path / "nope")
    c = bts._baseline_age_cell("aero")
    assert c.tone == "grey"
    assert c.label == "none"


def test_baseline_age_cell_fresh_is_green(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "BASELINE_ROOT", tmp_path)
    desktop = tmp_path / "aero" / "desktop"
    desktop.mkdir(parents=True)
    (desktop / "home.png").write_bytes(b"png")
    c = bts._baseline_age_cell("aero")
    assert c.tone == "green"
    assert c.label.endswith("d")


def test_baseline_age_cell_stale_is_red(bts, tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(bts, "BASELINE_ROOT", tmp_path)
    desktop = tmp_path / "aero" / "desktop"
    desktop.mkdir(parents=True)
    p = desktop / "home.png"
    p.write_bytes(b"png")
    # Mtime 40 days ago.
    old = p.stat().st_mtime - 40 * 86400
    os.utime(p, (old, old))
    c = bts._baseline_age_cell("aero")
    assert c.tone == "red"


def test_baseline_age_cell_medium_is_yellow(bts, tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(bts, "BASELINE_ROOT", tmp_path)
    desktop = tmp_path / "aero" / "desktop"
    desktop.mkdir(parents=True)
    p = desktop / "home.png"
    p.write_bytes(b"png")
    old = p.stat().st_mtime - 14 * 86400
    os.utime(p, (old, old))
    c = bts._baseline_age_cell("aero")
    assert c.tone == "yellow"


def test_vision_cell_marker_present_is_green(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "MONOREPO_ROOT", tmp_path)
    (tmp_path / "aero").mkdir()
    (tmp_path / "aero" / ".vision-reviewed").write_text("ok")
    c = bts._vision_cell("aero", "shipping")
    assert c.tone == "green"


def test_vision_cell_shipping_without_marker_is_yellow(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "MONOREPO_ROOT", tmp_path)
    (tmp_path / "aero").mkdir()
    c = bts._vision_cell("aero", "shipping")
    assert c.tone == "yellow"


def test_vision_cell_incubating_is_grey(bts, tmp_path, monkeypatch):
    monkeypatch.setattr(bts, "MONOREPO_ROOT", tmp_path)
    c = bts._vision_cell("aero", "incubating")
    assert c.tone == "grey"


# ---------------- _combine_cells ----------------


def test_combine_red_wins(bts):
    combined = bts._combine_cells(
        [
            bts.CellStatus(tone="green", label="pass"),
            bts.CellStatus(tone="red", label="fail", detail="hero leak"),
            bts.CellStatus(tone="yellow", label="warn"),
        ]
    )
    assert combined.tone == "red"
    assert combined.detail == "hero leak"


def test_combine_yellow_over_grey(bts):
    combined = bts._combine_cells(
        [
            bts.CellStatus(tone="grey", label="skip"),
            bts.CellStatus(tone="yellow", label="warn"),
        ]
    )
    assert combined.tone == "yellow"


def test_combine_all_green_is_green(bts):
    combined = bts._combine_cells(
        [
            bts.CellStatus(tone="green", label="pass"),
            bts.CellStatus(tone="green", label="pass"),
        ]
    )
    assert combined.tone == "green"


def test_combine_grey_and_green_is_green(bts):
    # Per docstring: grey only wins when no green is present.
    combined = bts._combine_cells(
        [
            bts.CellStatus(tone="grey", label="skip"),
            bts.CellStatus(tone="green", label="pass"),
        ]
    )
    assert combined.tone == "green"


# ---------------- render_html ----------------


def test_render_html_contains_expected_columns(bts):
    row = bts.ThemeRow(
        slug="aero",
        stage="shipping",
        stage_source_exists=True,
        summary="A summary.",
        owner="nick",
        last_checked="2026-04-26",
    )
    row.cells = {
        "stage": bts.CellStatus(tone="green", label="shipping"),
        "boot": bts.CellStatus(tone="green", label="boots"),
        "baseline": bts.CellStatus(tone="green", label="3d"),
        "microcopy": bts.CellStatus(tone="green", label="pass"),
        "images": bts.CellStatus(tone="green", label="pass"),
        "vision": bts.CellStatus(tone="yellow", label="needed"),
    }
    html = bts.render_html([row])
    assert "Theme status" in html
    assert "aero" in html
    assert "Stage" in html
    assert "Boot smoke" in html
    assert "Baseline age" in html
    assert "Microcopy distinct" in html
    assert "Images unique" in html
    assert "Vision reviewed" in html
    # Legend present.
    assert "legend" in html
    # Summary passed through.
    assert "A summary." in html


def test_render_html_is_deterministic_without_clock(bts):
    """Critical for the CI auto-commit path: two back-to-back renders
    of the same data must produce byte-identical HTML so `--check`
    doesn't ping-pong."""
    row = bts.ThemeRow(
        slug="aero",
        stage="shipping",
        stage_source_exists=True,
        summary="",
        owner="",
        last_checked="",
    )
    row.cells = {
        k: bts.CellStatus(tone="green", label="pass")
        for k in ("stage", "boot", "baseline", "microcopy", "images", "vision")
    }
    h1 = bts.render_html([row])
    h2 = bts.render_html([row])
    assert h1 == h2


# ---------------- CLI ----------------


def test_cli_check_fails_when_missing(bts, tmp_path):
    out = tmp_path / "nope.html"
    rc = bts.main(["--check", "--out", str(out)])
    assert rc == 1


def test_cli_writes_file(bts, tmp_path):
    out = tmp_path / "out" / "index.html"
    rc = bts.main(["--out", str(out)])
    assert rc == 0
    assert out.is_file()
    assert "<!doctype html>" in out.read_text(encoding="utf-8").lower()
