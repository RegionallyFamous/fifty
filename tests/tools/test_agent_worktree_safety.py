from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "agent-worktree.py"


def test_prune_creates_backup_tag_and_stashes_before_remove() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "def _backup_branch_before_prune(" in text
    assert '"tag", backup_tag, branch' in text
    assert '"stash",' in text
    assert "agent-worktree-prune" in text
    assert '"worktree", "remove", str(wt_path)' in text
    assert '"worktree", "remove", "--force", str(wt_path)' not in text
