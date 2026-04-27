"""Tests for `check_visual_baseline_present`.

The default visual gate (`bin/snap.py diff`) only flags routes whose
PNG differs from the committed baseline. A theme with NO baseline
files at all therefore looks "green" because there's nothing to
diff. This invariant is the upstream shield: every SHIPPING theme
must ship at least one baseline PNG, or the check fails. Incubating
themes are exempt (baselines are auto-generated when the theme is
promoted to shipping — see .github/workflows/first-baseline.yml).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _import_check(monkeypatch, theme_root: Path):
    repo_root = Path(__file__).resolve().parent.parent.parent
    bin_dir = repo_root / "bin"
    if str(bin_dir) not in sys.path:
        sys.path.insert(0, str(bin_dir))
    import check  # noqa: WPS433

    monkeypatch.setattr(check, "ROOT", theme_root)
    monkeypatch.setattr(check, "MONOREPO_ROOT", theme_root.parent)
    return check


def test_missing_baseline_dir_fails(tmp_path, monkeypatch):
    theme = tmp_path / "fresh-theme"
    theme.mkdir()
    monkeypatch.delenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", raising=False)
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert not r.passed and not r.skipped
    assert "tests/visual-baseline/fresh-theme" in " ".join(r.details)


def test_empty_baseline_dir_fails(tmp_path, monkeypatch):
    theme = tmp_path / "empty-baseline"
    theme.mkdir()
    (tmp_path / "tests" / "visual-baseline" / theme.name).mkdir(parents=True)
    monkeypatch.delenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", raising=False)
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert not r.passed and not r.skipped
    assert "no PNGs" in " ".join(r.details)


def test_baseline_with_pngs_passes(tmp_path, monkeypatch):
    theme = tmp_path / "good-theme"
    theme.mkdir()
    base = tmp_path / "tests" / "visual-baseline" / theme.name / "desktop"
    base.mkdir(parents=True)
    (base / "home.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.delenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", raising=False)
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert r.passed and not r.skipped


def test_escape_hatch_skips(tmp_path, monkeypatch):
    theme = tmp_path / "fixture-theme"
    theme.mkdir()
    monkeypatch.setenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", "1")
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert r.skipped


def _write_readiness(theme: Path, stage: str) -> None:
    (theme / "readiness.json").write_text(
        json.dumps(
            {
                "stage": stage,
                "summary": "test theme",
                "owner": "test",
                "last_checked": "2026-04-27",
                "notes": "",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_incubating_theme_skips_even_without_baselines(tmp_path, monkeypatch):
    """An incubating theme has no baseline dir yet — the auto-promotion
    workflow (.github/workflows/first-baseline.yml) generates baselines
    and flips to shipping. The check must SKIP (not FAIL) so an
    incubating theme can land on a PR without tripping the gate."""
    theme = tmp_path / "new-theme"
    theme.mkdir()
    _write_readiness(theme, "incubating")
    monkeypatch.delenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", raising=False)
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert r.skipped, (
        f"incubating theme must skip the baseline check; got passed={r.passed} "
        f"skipped={r.skipped} details={r.details}"
    )
    assert "incubating" in " ".join(r.details).lower()


def test_retired_theme_skips_even_without_baselines(tmp_path, monkeypatch):
    """A retired theme is kept on disk for provenance but excluded from
    CI gates — baselines don't have to exist."""
    theme = tmp_path / "retired-theme"
    theme.mkdir()
    _write_readiness(theme, "retired")
    monkeypatch.delenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", raising=False)
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert r.skipped


def test_shipping_theme_still_fails_without_baselines(tmp_path, monkeypatch):
    """A theme that explicitly claims stage=shipping MUST have
    baselines. Pins the original contract: the new stage-gate relaxes
    for incubating only, never for shipping."""
    theme = tmp_path / "ship-theme"
    theme.mkdir()
    _write_readiness(theme, "shipping")
    monkeypatch.delenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", raising=False)
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert not r.passed and not r.skipped


def test_missing_readiness_falls_back_to_shipping(tmp_path, monkeypatch):
    """The six original themes have readiness.json already; the fallback
    default for a theme without one is stage=shipping (see
    _readiness.py docstring). Therefore missing readiness must still
    FAIL without baselines, preserving the original guard for the
    legacy case."""
    theme = tmp_path / "legacy-theme"
    theme.mkdir()
    monkeypatch.delenv("FIFTY_SKIP_VISUAL_BASELINE_CHECK", raising=False)
    check = _import_check(monkeypatch, theme)
    r = check.check_visual_baseline_present()
    assert not r.passed and not r.skipped
