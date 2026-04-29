#!/usr/bin/env python3
"""Summarize self-healing factory-defect artifacts.

`bin/design_unblock.py` writes `tmp/runs/<run-id>/factory-defects.jsonl`
whenever a repair clears blockers. This helper is intentionally read-only:
it lets an operator see which fixes still need deterministic tooling without
opening the full STATUS.md or batch JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _read_defects(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "factory-defects.jsonl"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _summarize(run_dir: Path) -> int:
    defects = _read_defects(run_dir)
    needs_tooling = [
        defect for defect in defects if defect.get("tooling_status") == "needs-tooling"
    ]
    manual_review = [
        defect for defect in defects if defect.get("tooling_status") == "manual-review"
    ]
    covered = [defect for defect in defects if defect.get("tooling_status") == "covered-by-recipe"]
    print(f"# Factory Defects: {run_dir}")
    print(f"total: {len(defects)}")
    print(f"needs_tooling: {len(needs_tooling)}")
    print(f"manual_review: {len(manual_review)}")
    print(f"covered_by_recipe: {len(covered)}")
    if needs_tooling:
        print()
        print("## Needs deterministic tooling")
        for defect in needs_tooling:
            suggested = ", ".join(defect.get("suggested_files") or []) or "n/a"
            print(
                f"- {defect.get('category', 'unknown')}: "
                f"{defect.get('promotion_target', 'manual-review')} "
                f"({suggested})"
            )
    return 1 if needs_tooling else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    summarize = sub.add_parser("summarize", help="Summarize one tmp/runs/<run-id> folder.")
    summarize.add_argument("run_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "summarize":
        if not args.run_dir.is_dir():
            raise SystemExit(f"run-dir does not exist: {args.run_dir}")
        return _summarize(args.run_dir)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
