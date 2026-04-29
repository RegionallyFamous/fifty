#!/usr/bin/env python3
"""Report changed-theme scope for hooks and CI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import resolve_changed_scope


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify changed files into theme/infra scope.")
    parser.add_argument("--base", default=None, help="Git base ref, compared as <base>...HEAD.")
    parser.add_argument("--staged", action="store_true", help="Inspect only staged changes.")
    parser.add_argument(
        "--no-untracked",
        action="store_true",
        help="Do not include untracked files when inspecting the worktree.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "shell"),
        default="json",
        help="Output format. `shell` is hook-friendly KEY=value lines.",
    )
    args = parser.parse_args()

    scope = resolve_changed_scope(
        base=args.base,
        staged=args.staged,
        include_untracked=not args.no_untracked,
    )
    if args.format == "json":
        print(scope.to_json())
        return 0

    print(f"themes={' '.join(scope.themes)}")
    print(f"has_themes={'true' if scope.themes else 'false'}")
    print(f"all_themes_required={'true' if scope.all_themes_required else 'false'}")
    print(f"has_repo_infra_changes={'true' if scope.has_repo_infra_changes else 'false'}")
    print(f"docs_only={'true' if scope.docs_only else 'false'}")
    print(f"reason={scope.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
