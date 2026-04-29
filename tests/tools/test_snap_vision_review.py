from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "bin" / "snap-vision-review.py"


def test_vision_review_prints_pre_call_progress() -> None:
    src = SCRIPT.read_text(encoding="utf-8")

    assert "for index, item in enumerate(items, start=1):" in src
    assert '">> reviewing {index}/{len(items)} {item.viewport}/{item.route}"' in src
    assert "flush=True" in src
