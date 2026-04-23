"""Tests for the read-side mirror of the heuristic-finding allowlist
in `bin/check.py`.

`bin/snap.py` owns the canonical write-time apply (`_apply_allowlist_to_findings`).
`bin/check.py` ships a small read-only mirror so the static gate
honors the same allowlist when re-reading old findings.json files.

These tests exist for two reasons:

1. Behaviour on synthetic findings -- "kind matches and fingerprint
   matches" is the hot path for every finding the gate sees, and
   it's easy to break (e.g. compare by `selector` only and miss
   findings that emit a `fingerprint`).
2. Drift detection -- if snap.py's `_finding_fingerprint` ever
   evolves (e.g. adds a 3rd fallback field), the check.py mirror
   has to evolve with it. The cross-implementation test below
   constructs a synthetic finding and asserts both functions
   return the same fingerprint string.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _import_check():
    repo_root = Path(__file__).resolve().parent.parent.parent
    bin_dir = repo_root / "bin"
    if str(bin_dir) not in sys.path:
        sys.path.insert(0, str(bin_dir))
    import check  # noqa: WPS433
    return check


def _import_snap():
    repo_root = Path(__file__).resolve().parent.parent.parent
    bin_dir = repo_root / "bin"
    if str(bin_dir) not in sys.path:
        sys.path.insert(0, str(bin_dir))
    import snap  # noqa: WPS433
    return snap


# ---------------------------------------------------------------------------
# _load_axe_allowlist: missing / malformed / well-formed
# ---------------------------------------------------------------------------
def test_load_returns_empty_when_file_missing(tmp_path, monkeypatch):
    check = _import_check()
    missing = tmp_path / "absent.json"
    monkeypatch.setattr(check, "_AXE_ALLOWLIST_PATH", missing)
    assert check._load_axe_allowlist() == {}


def test_load_returns_empty_when_file_malformed(tmp_path, monkeypatch):
    check = _import_check()
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(check, "_AXE_ALLOWLIST_PATH", bad)
    assert check._load_axe_allowlist() == {}


def test_load_well_formed(tmp_path, monkeypatch):
    check = _import_check()
    good = tmp_path / "ok.json"
    good.write_text(
        json.dumps(
            {
                "selvedge:wide:checkout-filled": {
                    "element-overflow-x": ["fp-a", "fp-b"]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "_AXE_ALLOWLIST_PATH", good)
    out = check._load_axe_allowlist()
    assert "selvedge:wide:checkout-filled" in out
    # Sets, not lists, for O(1) membership in the hot loop:
    assert out["selvedge:wide:checkout-filled"]["element-overflow-x"] == {
        "fp-a", "fp-b"
    }


# ---------------------------------------------------------------------------
# _axe_finding_is_allowlisted: the predicate the check uses per finding
# ---------------------------------------------------------------------------
def test_finding_with_matching_kind_and_fingerprint_is_allowlisted():
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "element-overflow-x", "fingerprint": "fp-a"}
    assert check._axe_finding_is_allowlisted(
        allow, "selvedge", "wide", "checkout-filled", f
    )


def test_finding_falls_back_to_selector_when_no_fingerprint():
    """Mirrors snap.py:_finding_fingerprint precedence."""
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {".cart .total"}}}
    f = {"kind": "element-overflow-x", "selector": ".cart .total"}
    assert check._axe_finding_is_allowlisted(
        allow, "selvedge", "wide", "checkout-filled", f
    )


def test_finding_with_no_fingerprint_or_selector_is_not_allowlisted():
    """Snap.py policy: such findings are unconditional failures."""
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "element-overflow-x", "message": "no addressable target"}
    assert not check._axe_finding_is_allowlisted(
        allow, "selvedge", "wide", "checkout-filled", f
    )


def test_finding_with_wrong_kind_is_not_allowlisted():
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "color-contrast", "fingerprint": "fp-a"}
    assert not check._axe_finding_is_allowlisted(
        allow, "selvedge", "wide", "checkout-filled", f
    )


def test_finding_in_unmapped_cell_is_not_allowlisted():
    check = _import_check()
    allow = {"selvedge:wide:home": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "element-overflow-x", "fingerprint": "fp-a"}
    assert not check._axe_finding_is_allowlisted(
        allow, "selvedge", "wide", "checkout-filled", f
    )


def test_already_marked_allowlisted_finding_is_treated_as_allowlisted():
    """Defends against stale findings.json that snap.py demoted at
    write time -- we don't want to re-promote them just because the
    allowlist file changed since."""
    check = _import_check()
    f = {"kind": "color-contrast", "allowlisted": True}
    assert check._axe_finding_is_allowlisted({}, "selvedge", "wide", "home", f)


# ---------------------------------------------------------------------------
# Cross-implementation drift: check.py and snap.py MUST agree on the
# fingerprint of a synthetic finding. If snap.py evolves the precedence
# rule, this test fails and the check.py mirror has to be updated.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "finding",
    [
        {"fingerprint": "explicit-id-1"},
        {"selector": ".btn--primary"},
        {"fingerprint": "explicit-id-2", "selector": ".should-be-ignored"},
        {"unrelated_field": "value"},  # both should return None
        {},
    ],
)
def test_fingerprint_implementations_agree(finding):
    check = _import_check()
    snap = _import_snap()
    assert check._axe_finding_fingerprint(finding) == snap._finding_fingerprint(
        finding
    ), (
        "check.py and snap.py disagree on the fingerprint of the same "
        "finding -- if snap.py changed `_finding_fingerprint`, mirror "
        "the change in check.py:_axe_finding_fingerprint."
    )


def test_allowlist_key_format_matches_snap():
    """check.py constructs the lookup key inline as
    `{theme}:{viewport}:{route}`. snap.py exposes the same shape via
    `_allowlist_key`. If snap.py ever changes the separator or adds
    more components, this test fails."""
    snap = _import_snap()
    expected = snap._allowlist_key("selvedge", "wide", "checkout-filled")
    assert expected == "selvedge:wide:checkout-filled"
