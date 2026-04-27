"""Tests for `bin/snap.py`'s `boot` subcommand (Tier 1.1 boot-fatal smoke gate).

The boot smoke gate is a fast (~30s warm, ~2-3min cold) pre-shoot check
that catches "theme booted but immediately fataled" regressions without
paying the cost of a full 44-cell snap matrix. The surface under test:

  * `_boot_fatal_hits` / `_boot_warning_hits` -- pure regex-less
    substring matchers over response body + server log. They must:
     - be case-insensitive
     - dedupe (so "Fatal error:" appearing 5 times still reports once)
     - preserve insertion order from BOOT_FATAL_PATTERNS /
       BOOT_WARNING_PATTERNS so the first hit (most informative) is
       surfaced first
     - reject empty / None input without crashing

  * `_scan_log_for_fatals` -- reads the last 256 KiB of the server log.
    Must gracefully handle a missing file (theme boot crashed before
    the log was ever opened) and must tail, not head, because cold-boot
    blueprint chatter dwarfs the interesting end-of-log fatals.

  * `_probe_body` -- HTTP GET that returns a verdict dict. Contract:
    no exception escapes; a ConnectionError becomes `{"status": None,
    "error": "ConnectionError", ...}` so the caller doesn't need a
    try/except. HTTP errors (4xx/5xx) return the status AND scan the
    error-page body for fatals (because WP renders a nice <title> on
    fatal crashes even when it emits 500).

None of these tests boot a real Playground. `boot_smoke` itself is
exercised indirectly via the scanning helpers; integration testing is
via `bin/snap.py boot <theme>` run manually or by the nightly sweep.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def snap_mod(tmp_path, monkeypatch):
    """Import bin/snap.py with Playwright stubbed; repoint TMP_DIR at
    a tmp tree so `_write_boot_verdict` doesn't litter the real repo."""
    fake_playwright = type(sys)("playwright")
    fake_playwright.sync_api = type(sys)("playwright.sync_api")
    fake_playwright.sync_api.sync_playwright = lambda: None
    fake_playwright.sync_api.Error = Exception
    fake_playwright.sync_api.TimeoutError = Exception
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.sync_api", fake_playwright.sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "_snap_for_boot_test",
        BIN_DIR / "snap.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_snap_for_boot_test"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pytest.skip("snap.py exited at import (missing system dep)")

    tmp_tmp = tmp_path / "tmp"
    tmp_tmp.mkdir()
    monkeypatch.setattr(module, "TMP_DIR", tmp_tmp)
    return module


# ---------------------------------------------------------------------------
# _boot_fatal_hits
# ---------------------------------------------------------------------------


def test_fatal_hits_empty_input(snap_mod):
    assert snap_mod._boot_fatal_hits("") == []
    assert snap_mod._boot_fatal_hits(None) == []


def test_fatal_hits_clean_html(snap_mod):
    body = "<!doctype html><html><body>hello world</body></html>"
    assert snap_mod._boot_fatal_hits(body) == []


def test_fatal_hits_classic_fatal(snap_mod):
    body = (
        "<b>Fatal error:</b> Call to undefined function foo() in "
        "/wordpress/wp-content/themes/obel/functions.php on line 42"
    )
    hits = snap_mod._boot_fatal_hits(body)
    assert "Fatal error:" in hits
    assert "Call to undefined function" in hits


def test_fatal_hits_case_insensitive(snap_mod):
    body = "FATAL ERROR: something"
    assert "Fatal error:" in snap_mod._boot_fatal_hits(body)


def test_fatal_hits_dedupes(snap_mod):
    body = "Fatal error: a\nFatal error: b\nFatal error: c\n"
    hits = snap_mod._boot_fatal_hits(body)
    assert hits.count("Fatal error:") == 1


def test_fatal_hits_wp_critical_error_page(snap_mod):
    body = "<p>There has been a critical error on this website.</p>"
    assert "There has been a critical error on this website" in snap_mod._boot_fatal_hits(body)


def test_fatal_hits_wp_error_title(snap_mod):
    body = "<title>WordPress &rsaquo; Error</title>"
    assert "<title>WordPress &rsaquo; Error</title>" in snap_mod._boot_fatal_hits(body)


def test_fatal_hits_order_preserved(snap_mod):
    body = "Call to undefined method Foo::bar()\nFatal error: thing\nUncaught Error: something\n"
    hits = snap_mod._boot_fatal_hits(body)
    # BOOT_FATAL_PATTERNS ordering should win (Fatal error: comes first
    # in the tuple), not first-appearance-in-body ordering.
    assert hits.index("Fatal error:") < hits.index("Call to undefined method")
    assert hits.index("Fatal error:") < hits.index("Uncaught Error:")


def test_warning_hits_separates_from_fatals(snap_mod):
    body = "Deprecated: Using return value of strtolower()"
    assert snap_mod._boot_warning_hits(body) == ["Deprecated:"]
    assert snap_mod._boot_fatal_hits(body) == []


def test_warning_hits_does_not_catch_the_word_warning_mid_string(snap_mod):
    # We match "Warning:" (with colon), so "warning message" shouldn't
    # fire. This keeps the gate from tripping on theme copy that
    # mentions "warning" without a PHP prefix.
    body = "We have a warning message for you"
    # Note: substring match is case-insensitive, and "Warning:" is only
    # matched with the colon. "warning message" should NOT match.
    assert snap_mod._boot_warning_hits(body) == []


# ---------------------------------------------------------------------------
# _scan_log_for_fatals
# ---------------------------------------------------------------------------


def test_scan_log_missing_file(snap_mod, tmp_path):
    result = snap_mod._scan_log_for_fatals(tmp_path / "does-not-exist.log")
    assert result == {"fatals": [], "warns": [], "bytes": 0}


def test_scan_log_reads_tail(snap_mod, tmp_path):
    log = tmp_path / "server.log"
    # 300 KiB of blueprint chatter, then a fatal at the end.
    chatter = "blueprint step: installPlugin\n" * 5000
    tail = "Fatal error: Uncaught Error: Call to undefined function x()\n"
    log.write_text(chatter + tail, encoding="utf-8")
    result = snap_mod._scan_log_for_fatals(log, tail_kb=256)
    assert "Fatal error:" in result["fatals"]


def test_scan_log_does_not_flag_blueprint_noise(snap_mod, tmp_path):
    log = tmp_path / "server.log"
    # A real cold-boot log has plenty of benign lines that look like
    # they could fire the gate but shouldn't.
    log.write_text(
        "activateTheme step completed\n"
        "installPlugin step: woocommerce\n"
        "wp-cli: Success: WordPress installed successfully.\n",
        encoding="utf-8",
    )
    result = snap_mod._scan_log_for_fatals(log)
    assert result["fatals"] == []


def test_scan_log_tail_truncation_defeats_head_only_fatals(snap_mod, tmp_path):
    log = tmp_path / "server.log"
    # Fatal in the first 1 KiB, then 500 KiB of post-recovery chatter.
    log.write_text(
        "Fatal error: startup race -- recovered\n" + ("ok line\n" * 100_000),
        encoding="utf-8",
    )
    # Small tail -> fatal is outside the window -> shouldn't fire.
    # This is a deliberate trade-off: tail keeps smoke fast, and a fatal
    # that truly matters for boot will show up near the end (serving the
    # probe request) not buried 500 KiB deep.
    result = snap_mod._scan_log_for_fatals(log, tail_kb=32)
    assert result["fatals"] == []


def test_scan_log_handles_invalid_utf8(snap_mod, tmp_path):
    log = tmp_path / "server.log"
    log.write_bytes(b"\xff\xfe garbage bytes Fatal error: real one\n")
    result = snap_mod._scan_log_for_fatals(log)
    assert "Fatal error:" in result["fatals"]


# ---------------------------------------------------------------------------
# _probe_body
# ---------------------------------------------------------------------------


def test_probe_body_connection_refused_is_soft_failure(snap_mod):
    # Some port we're 99% sure is not bound. Any ConnectionError /
    # URLError should NOT raise; it should return status=None.
    result = snap_mod._probe_body("http://127.0.0.1:1/", timeout_s=1.0)
    assert result["status"] is None
    assert result["error"] is not None
    assert result["fatals"] == []


# ---------------------------------------------------------------------------
# _write_boot_verdict
# ---------------------------------------------------------------------------


def test_write_boot_verdict_writes_json(snap_mod):
    verdict = {
        "theme": "obel",
        "ok": True,
        "probes": [],
        "log_fatals": [],
        "log_warns": [],
        "reasons": [],
    }
    out = snap_mod._write_boot_verdict("obel", verdict)
    assert out.exists()
    assert out.name == "obel-boot.json"
    import json

    loaded = json.loads(out.read_text())
    assert loaded["theme"] == "obel"
    assert loaded["ok"] is True


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def test_cli_boot_subcommand_is_registered(snap_mod):
    parser = snap_mod.build_parser()
    args = parser.parse_args(["boot", "obel"])
    assert args.cmd == "boot"
    assert args.theme == "obel"
    assert args.all is False


def test_cli_boot_accepts_all_flag(snap_mod):
    parser = snap_mod.build_parser()
    args = parser.parse_args(["boot", "--all"])
    assert args.theme is None
    assert args.all is True


def test_cli_boot_accepts_cache_state(snap_mod):
    parser = snap_mod.build_parser()
    args = parser.parse_args(["boot", "obel", "--cache-state"])
    assert args.cache_state is True


def test_cli_boot_rejects_missing_theme_and_all(snap_mod, capsys):
    parser = snap_mod.build_parser()
    args = parser.parse_args(["boot"])
    # cmd_boot should return exit code 2 + print usage.
    rc = snap_mod.cmd_boot(args)
    assert rc == 2
