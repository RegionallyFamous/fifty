"""Tests for the smart-design-agent vision pipeline.

These tests exercise everything that does NOT require an Anthropic API
key. The contract is: the system must be runnable end-to-end in `--dry-run`
without secrets, so CI on PRs without `secrets.ANTHROPIC_API_KEY` can
still catch regressions in prompt building, JSON parsing, fingerprinting,
caching, and validation-CLI plumbing.

A separate (skipped-by-default) test module would cover the live API
path; we don't ship that yet because it requires an API key in CI and
would burn budget on every run. Once `FIFTY_VISION_REVIEW=1` becomes
default-on (PR 3 follow-up), we'll add `tests/vision/test_live_api.py`
gated on `os.environ.get('ANTHROPIC_API_KEY')`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "visual-regressions"

if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


def _load_reviewer_module():
    """Load `bin/snap-vision-review.py` as an importable module despite
    the hyphen in the filename (which prevents a normal `import`)."""
    spec = importlib.util.spec_from_file_location(
        "snap_vision_review", BIN_DIR / "snap-vision-review.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["snap_vision_review"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# _vision_lib.py
# ---------------------------------------------------------------------------


def test_estimate_cost_usd_input_only():
    import _vision_lib as vl
    cost = vl.estimate_cost_usd(1_000_000, 0, price_input_per_mtok=3.0, price_output_per_mtok=15.0)
    assert cost == pytest.approx(3.0)


def test_estimate_cost_usd_combined():
    import _vision_lib as vl
    cost = vl.estimate_cost_usd(2000, 800, price_input_per_mtok=3.0, price_output_per_mtok=15.0)
    assert cost == pytest.approx(0.018)


def test_fingerprint_is_stable_for_identical_inputs():
    import _vision_lib as vl
    a = vl.fingerprint_inputs(png_bytes=b"hello", intent_md="x", model="m1")
    b = vl.fingerprint_inputs(png_bytes=b"hello", intent_md="x", model="m1")
    assert a == b


def test_fingerprint_changes_when_any_input_changes():
    import _vision_lib as vl
    base = vl.fingerprint_inputs(png_bytes=b"hello", intent_md="x", model="m1")
    assert vl.fingerprint_inputs(png_bytes=b"hellO", intent_md="x", model="m1") != base
    assert vl.fingerprint_inputs(png_bytes=b"hello", intent_md="X", model="m1") != base
    assert vl.fingerprint_inputs(png_bytes=b"hello", intent_md="x", model="m2") != base
    assert vl.fingerprint_inputs(png_bytes=b"hello", intent_md="x", model="m1", extra="z") != base


def test_parse_findings_happy_path():
    import _vision_lib as vl
    raw = json.dumps(
        {
            "findings": [
                {
                    "kind": "vision:typography-overpowered",
                    "severity": "error",
                    "message": "Massive heading.",
                    "bbox": {"x": 10, "y": 20, "w": 300, "h": 100},
                    "rationale": "Hero copy consumes 70% of viewport height.",
                    "remedy_hint": "Drop to fontSize:4xl.",
                }
            ]
        }
    )
    out = vl.parse_findings_response(raw)
    assert len(out) == 1
    f = out[0]
    assert f["kind"] == "vision:typography-overpowered"
    assert f["severity"] == "error"
    assert f["bbox"] == {"x": 10, "y": 20, "w": 300, "h": 100}
    assert f["source"] == "vision"


def test_parse_findings_drops_unknown_kinds():
    import _vision_lib as vl
    raw = json.dumps(
        {
            "findings": [
                {"kind": "vision:hallucinated", "severity": "error", "message": "x", "rationale": "y"},
                {"kind": "vision:cta-buried", "severity": "warn", "message": "x", "rationale": "y"},
            ]
        }
    )
    out = vl.parse_findings_response(raw)
    assert [f["kind"] for f in out] == ["vision:cta-buried"]


def test_parse_findings_normalises_invalid_severity():
    import _vision_lib as vl
    raw = json.dumps(
        {"findings": [{"kind": "vision:cta-buried", "severity": "URGENT", "message": "x", "rationale": "y"}]}
    )
    out = vl.parse_findings_response(raw)
    assert out[0]["severity"] == "warn"


def test_parse_findings_strips_code_fence():
    import _vision_lib as vl
    inner = json.dumps({"findings": [{"kind": "vision:cta-buried", "severity": "info", "message": "m", "rationale": "r"}]})
    raw = f"```json\n{inner}\n```"
    out = vl.parse_findings_response(raw)
    assert len(out) == 1


def test_parse_findings_returns_empty_on_garbage():
    import _vision_lib as vl
    assert vl.parse_findings_response("not json") == []
    assert vl.parse_findings_response("") == []
    assert vl.parse_findings_response('{"not": "the right shape"}') == []


def test_today_spend_returns_zero_when_ledger_missing(tmp_path):
    import _vision_lib as vl
    assert vl.today_spend_usd(path=tmp_path / "no-ledger.jsonl") == 0.0


def test_append_ledger_round_trip(tmp_path):
    import _vision_lib as vl
    ledger = tmp_path / "spend.jsonl"
    vl.append_ledger(
        vl.LedgerEntry(
            timestamp_iso="2026-04-22T12:00:00+00:00",
            model="m",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        ),
        path=ledger,
    )
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l]
    assert len(rows) == 1
    assert rows[0]["cost_usd"] == 0.001


def test_review_image_dry_run_does_not_call_api(tmp_path, monkeypatch):
    import _vision_lib as vl
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def boom(*a, **kw):
        raise AssertionError("urlopen should never be called in dry-run")

    monkeypatch.setattr(vl.urllib.request, "urlopen", boom)
    png = list(FIXTURES.glob("*.png"))[0]
    resp = vl.review_image(
        png_path=png,
        intent_md="rubric",
        theme="x",
        route="home",
        viewport="desktop",
        dry_run=True,
        ledger_path=tmp_path / "spend.jsonl",
    )
    assert resp.dry_run is True
    assert resp.findings == []
    assert resp.cost_usd == 0.0


def test_review_image_raises_when_no_api_key(tmp_path, monkeypatch):
    import _vision_lib as vl
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    png = list(FIXTURES.glob("*.png"))[0]
    with pytest.raises(vl.ApiKeyMissingError):
        vl.review_image(
            png_path=png,
            intent_md="rubric",
            theme="x",
            route="home",
            viewport="desktop",
            dry_run=False,
            ledger_path=tmp_path / "spend.jsonl",
        )


def test_budget_assertion_blocks_when_already_over(tmp_path, monkeypatch):
    import _vision_lib as vl
    ledger = tmp_path / "spend.jsonl"
    # Pre-load a row that pushes today's spend just under the cap.
    import datetime as dt
    today = dt.datetime.now(dt.timezone.utc).isoformat()
    ledger.write_text(json.dumps({"timestamp": today, "cost_usd": 19.99}) + "\n")
    with pytest.raises(vl.BudgetExceededError):
        vl.assert_under_budget(0.05, cap_usd=20.0, ledger_path=ledger)


# ---------------------------------------------------------------------------
# Fixture set sanity
# ---------------------------------------------------------------------------


def test_fixture_manifest_well_formed():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert "fixtures" in manifest
    fixtures = manifest["fixtures"]
    assert len(fixtures) == 10
    regs = [f for f in fixtures if f["kind"] == "regression"]
    wd = [f for f in fixtures if f["kind"] == "well-designed"]
    assert len(regs) == 5
    assert len(wd) == 5
    for f in fixtures:
        assert (FIXTURES / f["file"]).exists(), f"missing PNG: {f['file']}"
        assert isinstance(f["expected_findings"], list)
        assert isinstance(f["forbidden_findings"], list)
    accept = manifest["_meta"]["acceptance"]
    for k in (
        "regressions_caught_min",
        "well_designed_false_positives_max",
        "precision_min",
        "recall_min",
    ):
        assert k in accept


def test_fixture_expected_kinds_are_in_allowed_set():
    """Every kind named in the manifest must exist in the vision_lib's
    allowed set; otherwise the reviewer would silently drop it."""
    import _vision_lib as vl
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    for f in manifest["fixtures"]:
        for k in f["expected_findings"] + f["forbidden_findings"]:
            assert k in vl.ALLOWED_FINDING_KINDS, f"{f['file']}: unknown kind {k}"


# ---------------------------------------------------------------------------
# snap-vision-review.py CLI (dry-run)
# ---------------------------------------------------------------------------


def test_cli_help_loads(run_bin_script):
    res = run_bin_script("snap-vision-review.py", "--help")
    assert res.returncode == 0
    assert "vision-based design reviewer" in res.stdout.lower()


def test_cli_validate_dry_run_exits_clean(run_bin_script):
    res = run_bin_script("snap-vision-review.py", "--validate", str(FIXTURES), "--dry-run")
    assert res.returncode == 0, f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    assert "validating against 10 fixtures" in res.stdout
    # Dry-run intentionally produces 0/5 caught; assertion is that the
    # CLI exits 0 anyway so CI without a key passes.


def test_cli_no_theme_no_validate_fails():
    """Calling the CLI with neither a theme nor --validate is a usage error."""
    mod = _load_reviewer_module()
    rc = mod.main([])
    assert rc == 2


def test_cli_unknown_theme_fails():
    mod = _load_reviewer_module()
    rc = mod.main(["this-theme-does-not-exist"])
    assert rc == 2


def test_cli_dry_run_is_read_only(run_bin_script, tmp_path, monkeypatch):
    """Critical contract: --dry-run must NOT touch tmp/snaps. A previous
    iteration wrote .vision-fingerprint and .review.png in dry-run, which
    would clobber real findings on a subsequent live run."""
    # Build a fake snap tree with one PNG + one design-intent.md + a
    # findings.json that already has a vision finding we don't want erased.
    fake_theme = tmp_path / "obel"
    fake_theme.mkdir()
    (fake_theme / "theme.json").write_text("{}")
    (fake_theme / "design-intent.md").write_text(
        "# Voice\nx\n## Palette\nx\n## Typography\nx\n" + ("filler\n" * 60)
    )
    snaps = tmp_path / "tmp" / "snaps" / "obel" / "desktop"
    snaps.mkdir(parents=True)
    # Tiny but valid PNG (1x1 white)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8"
        b"\xff\xff?\x00\x05\xfe\x02\xfe\xa3\x9d\x06|\x00\x00\x00\x00IEND"
        b"\xaeB`\x82"
    )
    (snaps / "home.png").write_bytes(png_bytes)
    (snaps / "home.findings.json").write_text(json.dumps({
        "findings": [
            {"kind": "color-contrast", "severity": "error", "source": "axe"},
            {"kind": "vision:cta-buried", "severity": "warn", "source": "vision", "message": "preserved"},
        ]
    }))

    # Run reviewer with REPO_ROOT redirected to the fake tree
    res = run_bin_script(
        "snap-vision-review.py", "obel", "--dry-run",
        env={"PYTHONPATH": str(BIN_DIR)},
        cwd=tmp_path,
    )
    # Whatever happens, we only assert about disk effects:
    assert not list(snaps.glob("*.vision-fingerprint")), \
        f"dry-run wrote fingerprint files: {list(snaps.glob('*.vision-fingerprint'))}"
    assert not list(snaps.glob("*.review.png")), \
        f"dry-run wrote review PNGs: {list(snaps.glob('*.review.png'))}"
    after = json.loads((snaps / "home.findings.json").read_text())
    msgs = [f.get("message") for f in after["findings"] if f.get("source") == "vision"]
    assert "preserved" in msgs, f"dry-run clobbered existing vision finding; remaining: {after['findings']}"
