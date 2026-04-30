"""Tests for `check_allowlist_entries_resolve`.

The allowlist suppresses pre-existing heuristic findings so a theme
can ship while a known issue is on the to-fix queue. Typo'd entries
silently match nothing (they don't suppress and they don't fail), so
a real regression in the renamed route walks past the gate. This
invariant turns those orphan keys into a hard fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _import_check(monkeypatch, theme_root: Path, allowlist_path: Path):
    repo_root = Path(__file__).resolve().parent.parent.parent
    bin_dir = repo_root / "bin"
    if str(bin_dir) not in sys.path:
        sys.path.insert(0, str(bin_dir))
    import check  # noqa: WPS433

    monkeypatch.setattr(check, "ROOT", theme_root)
    monkeypatch.setattr(check, "MONOREPO_ROOT", theme_root.parent)
    monkeypatch.setattr(check, "_AXE_ALLOWLIST_PATH", allowlist_path)
    return check


def _make_theme(root: Path, name: str) -> Path:
    theme = root / name
    theme.mkdir()
    (theme / "theme.json").write_text("{}", encoding="utf-8")
    return theme


def test_missing_allowlist_skips(tmp_path, monkeypatch):
    theme = _make_theme(tmp_path, "obel")
    check = _import_check(monkeypatch, theme, tmp_path / "absent.json")
    r = check.check_allowlist_entries_resolve()
    assert r.skipped


def test_known_cells_pass(tmp_path, monkeypatch):
    theme = _make_theme(tmp_path, "selvedge")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"selvedge:desktop:checkout-filled": {"element-overflow-x": ["fp-a"]}}),
        encoding="utf-8",
    )
    check = _import_check(monkeypatch, theme, allow)
    r = check.check_allowlist_entries_resolve()
    assert r.passed and not r.skipped, r.details


def test_unknown_route_fails(tmp_path, monkeypatch):
    theme = _make_theme(tmp_path, "selvedge")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"selvedge:wide:nonexistent-route": {"element-overflow-x": ["fp"]}}),
        encoding="utf-8",
    )
    check = _import_check(monkeypatch, theme, allow)
    r = check.check_allowlist_entries_resolve()
    assert not r.passed and not r.skipped
    assert "nonexistent-route" in " ".join(r.details)


def test_unknown_viewport_fails(tmp_path, monkeypatch):
    theme = _make_theme(tmp_path, "selvedge")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"selvedge:not-a-viewport:checkout-filled": {"k": ["v"]}}),
        encoding="utf-8",
    )
    check = _import_check(monkeypatch, theme, allow)
    r = check.check_allowlist_entries_resolve()
    assert not r.passed and not r.skipped
    assert "not-a-viewport" in " ".join(r.details)


def test_unknown_theme_fails(tmp_path, monkeypatch):
    theme = _make_theme(tmp_path, "selvedge")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"ghost-theme:wide:checkout-filled": {"k": ["v"]}}),
        encoding="utf-8",
    )
    check = _import_check(monkeypatch, theme, allow)
    r = check.check_allowlist_entries_resolve()
    assert not r.passed and not r.skipped
    assert "ghost-theme" in " ".join(r.details)


def test_wildcard_theme_passes(tmp_path, monkeypatch):
    theme = _make_theme(tmp_path, "selvedge")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"*:desktop:checkout-filled": {"vision:typography-overpowered": ["*"]}}),
        encoding="utf-8",
    )
    check = _import_check(monkeypatch, theme, allow)
    r = check.check_allowlist_entries_resolve()
    assert r.passed and not r.skipped


def test_malformed_key_fails(tmp_path, monkeypatch):
    theme = _make_theme(tmp_path, "selvedge")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"only-two:parts": {"k": ["v"]}}),
        encoding="utf-8",
    )
    check = _import_check(monkeypatch, theme, allow)
    r = check.check_allowlist_entries_resolve()
    assert not r.passed and not r.skipped
    assert "malformed" in " ".join(r.details)
