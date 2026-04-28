#!/usr/bin/env python3
"""Fast, deterministic triage for common Fifty theme failures.

This script deliberately does not boot Playground. It reads the cheap evidence
first: recent snap findings, required playground payload files, and git tracking
state. Use it before spending minutes on a re-shoot.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, resolve_theme_root


def repo_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(MONOREPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def git_tracks(path: Path) -> bool:
    rel = repo_relpath(path)
    try:
        return (
            subprocess.run(
                ["git", "ls-files", "--error-unmatch", rel],
                cwd=MONOREPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
    except OSError:
        return True


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def placeholder_findings(theme: str) -> dict[str, list[str]]:
    snaps_root = MONOREPO_ROOT / "tmp" / "snaps" / theme
    by_viewport: dict[str, list[str]] = defaultdict(list)
    if not snaps_root.is_dir():
        return by_viewport
    for path in sorted(snaps_root.rglob("*.findings.json")):
        data = load_json(path)
        issues = data.get("issues") or data.get("findings") or []
        if not isinstance(issues, list):
            continue
        hit = False
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            msg = str(issue.get("message") or issue.get("title") or "").lower()
            if "placeholder" in msg and ("product image" in msg or "expected" in msg):
                hit = True
                break
        if hit:
            by_viewport[path.parent.name].append(path.stem.replace(".findings", ""))
    return by_viewport


def payload_state(theme_root: Path) -> list[str]:
    problems: list[str] = []
    images_dir = theme_root / "playground" / "images"
    content_dir = theme_root / "playground" / "content"
    product_photos = sorted(images_dir.glob("product-wo-*.jpg")) if images_dir.is_dir() else []
    category_covers = sorted(images_dir.glob("cat-*.jpg")) if images_dir.is_dir() else []

    required_if_present = [
        (product_photos, content_dir / "product-images.json", "product photographs"),
        (category_covers, content_dir / "category-images.json", "category covers"),
    ]
    for assets, map_path, label in required_if_present:
        if not assets:
            continue
        if not map_path.exists():
            problems.append(
                f"{repo_relpath(map_path)} is missing, but {len(assets)} {label} exist."
            )
        elif not git_tracks(map_path):
            problems.append(
                f"{repo_relpath(map_path)} exists but is untracked; raw GitHub will 404 it."
            )

    for path in [*product_photos, *category_covers]:
        if not git_tracks(path):
            problems.append(f"{repo_relpath(path)} is untracked; raw GitHub will 404 it.")
    return problems


def triage_placeholder_images(theme_root: Path) -> int:
    theme = theme_root.name
    findings = placeholder_findings(theme)
    payload_problems = payload_state(theme_root)

    print(f"Triage: {theme} placeholder images")
    print("=" * (len(theme) + 28))
    if findings:
        print("\nAffected latest snap findings:")
        for viewport, routes in sorted(findings.items()):
            print(f"  {viewport}: {', '.join(sorted(set(routes)))}")
    else:
        print("\nAffected latest snap findings: none found")

    if payload_problems:
        print("\nLikely root cause:")
        for problem in payload_problems:
            print(f"  - {problem}")
    elif findings:
        print("\nLikely root cause:")
        print("  - Runtime sideload failed despite local payloads existing and being tracked.")
        print("  - Check tmp/<theme>-server.log for wo-import.php / wo-configure.php download warnings.")
    else:
        print("\nLikely root cause: no active placeholder evidence in latest findings.")

    print("\nFast verification:")
    print(
        f"  python3 bin/check.py {theme} --quick --only "
        "product-images-json category-images-json placeholder-images"
    )
    print(
        f"  python3 bin/snap.py shoot {theme} --routes shop category home "
        "--viewports mobile desktop --no-skip"
    )

    return 1 if findings or payload_problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cheap triage before expensive snap/check loops.")
    parser.add_argument("theme", help="Theme slug or path.")
    parser.add_argument(
        "--check",
        default="placeholder-images",
        choices=["placeholder-images"],
        help="Triage family to run. Currently supports placeholder-images.",
    )
    args = parser.parse_args()

    theme_root = resolve_theme_root(args.theme)
    return triage_placeholder_images(theme_root)


if __name__ == "__main__":
    raise SystemExit(main())
