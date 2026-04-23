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
        json.dumps({"selvedge:wide:checkout-filled": {"element-overflow-x": ["fp-a", "fp-b"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "_AXE_ALLOWLIST_PATH", good)
    out = check._load_axe_allowlist()
    assert "selvedge:wide:checkout-filled" in out
    # Sets, not lists, for O(1) membership in the hot loop:
    assert out["selvedge:wide:checkout-filled"]["element-overflow-x"] == {"fp-a", "fp-b"}


# ---------------------------------------------------------------------------
# _axe_finding_is_allowlisted: the predicate the check uses per finding
# ---------------------------------------------------------------------------
def test_finding_with_matching_kind_and_fingerprint_is_allowlisted():
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "element-overflow-x", "fingerprint": "fp-a"}
    assert check._axe_finding_is_allowlisted(allow, "selvedge", "wide", "checkout-filled", f)


def test_finding_falls_back_to_selector_when_no_fingerprint():
    """Mirrors snap.py:_finding_fingerprint precedence."""
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {".cart .total"}}}
    f = {"kind": "element-overflow-x", "selector": ".cart .total"}
    assert check._axe_finding_is_allowlisted(allow, "selvedge", "wide", "checkout-filled", f)


def test_finding_with_no_fingerprint_or_selector_is_not_allowlisted():
    """Snap.py policy: such findings are unconditional failures."""
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "element-overflow-x", "message": "no addressable target"}
    assert not check._axe_finding_is_allowlisted(allow, "selvedge", "wide", "checkout-filled", f)


def test_finding_with_wrong_kind_is_not_allowlisted():
    check = _import_check()
    allow = {"selvedge:wide:checkout-filled": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "color-contrast", "fingerprint": "fp-a"}
    assert not check._axe_finding_is_allowlisted(allow, "selvedge", "wide", "checkout-filled", f)


def test_finding_in_unmapped_cell_is_not_allowlisted():
    check = _import_check()
    allow = {"selvedge:wide:home": {"element-overflow-x": {"fp-a"}}}
    f = {"kind": "element-overflow-x", "fingerprint": "fp-a"}
    assert not check._axe_finding_is_allowlisted(allow, "selvedge", "wide", "checkout-filled", f)


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
    assert check._axe_finding_fingerprint(finding) == snap._finding_fingerprint(finding), (
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


# ---------------------------------------------------------------------------
# Wildcard allowlist (vision:* findings have no DOM address).
#
# A cell entry whose selector list contains the sentinel "*" -- or that
# is empty -- matches every finding of that `kind` on that route, even
# when the finding has no fingerprint at all. This is how vision-source
# findings get baselined (they're whole-page critiques, not node-level
# DOM findings) without inventing a separate allowlist file.
# ---------------------------------------------------------------------------
def test_wildcard_selector_matches_finding_without_fingerprint():
    check = _import_check()
    allow = {"selvedge:mobile:home": {"vision:typography-overpowered": {"*"}}}
    f = {"kind": "vision:typography-overpowered", "source": "vision"}
    assert check._axe_finding_is_allowlisted(allow, "selvedge", "mobile", "home", f)


def test_wildcard_selector_matches_finding_even_with_fingerprint():
    """Wildcard subsumes specific selectors -- a `*` entry means
    "every instance of this kind on this route"."""
    check = _import_check()
    allow = {"chonk:desktop:shop": {"button-label-overflow": {"*"}}}
    f = {"kind": "button-label-overflow", "fingerprint": "any-selector"}
    assert check._axe_finding_is_allowlisted(allow, "chonk", "desktop", "shop", f)


def test_empty_selector_set_treated_as_wildcard():
    """An empty list / set in the JSON file is interpreted the same
    as `["*"]`. This keeps malformed-but-intentional cells (`{"kind": []}`)
    from being silently meaningless."""
    check = _import_check()
    allow = {"obel:wide:home": {"vision:hierarchy-flat": set()}}
    f = {"kind": "vision:hierarchy-flat"}
    assert check._axe_finding_is_allowlisted(allow, "obel", "wide", "home", f)


def test_wildcard_in_one_kind_does_not_leak_to_other_kinds():
    check = _import_check()
    allow = {"aero:mobile:shop": {"vision:brand-violation": {"*"}}}
    f_other_kind = {"kind": "vision:color-clash"}
    assert not check._axe_finding_is_allowlisted(allow, "aero", "mobile", "shop", f_other_kind)


def test_specific_selector_still_required_when_no_wildcard_present():
    """Without a wildcard sentinel, the existing fingerprint-matching
    behaviour is preserved -- this guards against a refactor that
    accidentally allowlists everything."""
    check = _import_check()
    allow = {"chonk:desktop:home": {"element-overflow-x": {"div.specific"}}}
    f_no_fp = {"kind": "element-overflow-x", "message": "no selector"}
    assert not check._axe_finding_is_allowlisted(allow, "chonk", "desktop", "home", f_no_fp)
    f_diff_fp = {"kind": "element-overflow-x", "selector": "div.different"}
    assert not check._axe_finding_is_allowlisted(allow, "chonk", "desktop", "home", f_diff_fp)


def test_snap_apply_wildcard_demotes_findings_without_fingerprint(monkeypatch):
    """snap.py:_apply_allowlist_to_findings is the WRITE-side mirror.
    A wildcard cell must demote a vision finding (no fingerprint) the
    same way check.py:_axe_finding_is_allowlisted reads it."""
    snap = _import_snap()
    fake_allowlist = {"selvedge:mobile:home": {"vision:typography-overpowered": ["*"]}}
    monkeypatch.setattr(snap, "_load_allowlist", lambda: fake_allowlist)
    findings = [
        {
            "kind": "vision:typography-overpowered",
            "severity": "error",
            "source": "vision",
        },
        {
            "kind": "vision:other-kind",
            "severity": "error",
            "source": "vision",
        },
    ]
    n = snap._apply_allowlist_to_findings("selvedge", "mobile", "home", findings)
    assert n == 1
    assert findings[0]["severity"] == "info"
    assert findings[0]["allowlisted"] is True
    assert findings[1]["severity"] == "error"  # untouched
