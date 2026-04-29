from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRE_PUSH = ROOT / ".githooks" / "pre-push"


def test_pre_push_classifies_snap_infrastructure_timeouts() -> None:
    src = PRE_PUSH.read_text(encoding="utf-8")

    assert "SNAP_INFRASTRUCTURE_TIMEOUT" in src
    assert "Playground infrastructure timeout" in src
    assert "No visual or accessibility findings were emitted" in src
    assert "visual or accessibility regressions" in src
    assert 'tee "$snap_check_log"' in src
