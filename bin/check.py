#!/usr/bin/env python3
"""Single-command validator. Run before every commit.

This is the "make test" of the Obel theme. It runs every check the project
cares about and exits non-zero if any of them fail.

Checks performed:
  1. JSON validity for theme.json and styles/*.json
  2. PHP syntax for every .php file
  3. Block-name validity in theme.json (via validate-theme-json.py)
  4. No `!important` in code (only in AGENTS.md and other rule docs, which is allowed)
  5. No stray .css files (only style.css is allowed)
  6. No block prefixes other than core/* and woocommerce/* in templates/parts
  7. No AI-fingerprint vocabulary in user-facing files
  8. No hardcoded hex colors in templates/parts/patterns
  9. No hardcoded px/em/rem dimensions in style= attributes (outside allowlist)
 10. No duplicate template files in templates/

Usage:
    python3 bin/check.py            # run everything
    python3 bin/check.py --offline  # skip the network-dependent block check
    python3 bin/check.py --quick    # skip the network check, run everything else

Output: one line per check, with PASS/FAIL/SKIP. Exit code 0 if all pass.

Requires Python 3.8+ and `php` on PATH for PHP syntax check (PHP step is
skipped with a warning if `php` is not available).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ANSI colors. Disabled when not a tty.
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
GREEN = "\033[32m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""
YELLOW = "\033[33m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""


class Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = True
        self.skipped = False
        self.details: list[str] = []

    def fail(self, detail: str) -> None:
        self.passed = False
        self.details.append(detail)

    def skip(self, reason: str) -> None:
        self.skipped = True
        self.details.append(reason)

    def render(self) -> str:
        if self.skipped:
            label = f"{YELLOW}SKIP{RESET}"
        elif self.passed:
            label = f"{GREEN}PASS{RESET}"
        else:
            label = f"{RED}FAIL{RESET}"
        line = f"  [{label}] {self.name}"
        for detail in self.details:
            line += f"\n         {DIM}{detail}{RESET}"
        return line


def check_json_validity() -> Result:
    r = Result("JSON validity (theme.json + styles/*.json)")
    targets = [ROOT / "theme.json"] + sorted((ROOT / "styles").glob("*.json"))
    for path in targets:
        if not path.exists():
            r.fail(f"missing: {path.relative_to(ROOT)}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            r.fail(f"{path.relative_to(ROOT)}: {exc}")
    if r.passed and not r.skipped:
        r.details.append(f"{len(targets)} files checked")
    return r


def check_php_syntax() -> Result:
    r = Result("PHP syntax (functions.php + patterns/*.php)")
    if not shutil.which("php"):
        r.skip("php not found on PATH")
        return r
    php_files = [ROOT / "functions.php"] + sorted((ROOT / "patterns").glob("*.php"))
    for path in php_files:
        if not path.exists():
            continue
        proc = subprocess.run(
            ["php", "-l", str(path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            r.fail(f"{path.relative_to(ROOT)}: {proc.stderr.strip() or proc.stdout.strip()}")
    if r.passed and not r.skipped:
        r.details.append(f"{len(php_files)} files checked")
    return r


def check_block_names(offline: bool) -> Result:
    r = Result("Block-name validity (validate-theme-json.py)")
    if offline:
        r.skip("--offline / --quick passed")
        return r
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "validate-theme-json.py")],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        r.fail(proc.stdout.strip() or proc.stderr.strip())
    return r


def check_index_in_sync() -> Result:
    r = Result("INDEX.md in sync (build-index.py --check)")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "build-index.py"), "--check"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        r.fail((proc.stderr or proc.stdout).strip())
    return r


# Files where `!important` is allowed because they document the rule itself.
IMPORTANT_RULE_DOCS = {"AGENTS.md", "README.md", "readme.txt", "CHANGELOG.md"}


def check_no_important() -> Result:
    r = Result("No `!important` in code")
    pattern = re.compile(r"!important")
    for path in iter_files((".json", ".php", ".html", ".css")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in IMPORTANT_RULE_DOCS:
            continue
        if rel.startswith("bin/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                r.fail(f"{rel}:{lineno}: {line.strip()}")
    return r


def check_no_stray_css() -> Result:
    r = Result("No stray .css files (only style.css allowed)")
    for path in ROOT.rglob("*.css"):
        if any(part in {".git", "node_modules", "vendor"} for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel != "style.css":
            r.fail(rel)
    return r


def check_block_prefixes() -> Result:
    r = Result("Only core/* and woocommerce/* blocks in templates/parts/patterns")
    block_re = re.compile(r"<!--\s*wp:([a-z0-9-]+)/")
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not (rel.startswith("templates/") or rel.startswith("parts/") or rel.startswith("patterns/")):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for ns in block_re.findall(line):
                if ns not in ("core", "woocommerce"):
                    r.fail(f"{rel}:{lineno}: forbidden namespace '{ns}'")
    return r


# Vocabulary that signals AI-generated marketing copy. The rule docs themselves
# (AGENTS.md, CHANGELOG.md) reference these words and are excluded.
AI_FINGERPRINT_RE = re.compile(
    r"—|\bleverage\b|\bcomprehensive\b|\bseamless\b|\bdelve\b|\btapestry\b|\brobust\b",
    re.IGNORECASE,
)
AI_FINGERPRINT_TARGETS = ("README.md", "readme.txt", "style.css")


def check_no_hardcoded_colors() -> Result:
    """Scan templates/parts/patterns for hardcoded hex colors.

    The Cover block legitimately outputs background-color on its inner span
    when a custom overlay color is set (customOverlayColor). Since we've
    switched all covers to named palette colors, any remaining hex literal
    is a mistake.

    Allowlist: lines containing 'rgba(' are permitted (used for gradients and
    shadows defined in theme.json, not in markup).
    """
    r = Result("No hardcoded hex colors in templates/parts/patterns")
    hex_re = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
    skip_dirs = {"templates/", "parts/", "patterns/"}
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "rgba(" in line:
                continue
            if hex_re.search(line):
                r.fail(f"{rel}:{lineno}: {line.strip()}")
    return r


def check_no_hardcoded_dimensions() -> Result:
    """Scan templates/parts/patterns for hardcoded px/em/rem values in style=
    attributes, excluding common known-safe values.

    Allowlist:
      - 1px, 2px  (borders)
      - min-height  (Cover block canonical attribute output)
      - flex-basis  (Column block width attribute output — no token equivalent)
      - width/height on block wrappers (structural layout, not design token)
    """
    r = Result("No hardcoded dimensions in templates/parts/patterns style= attributes")
    # Match pixel/em/rem literals inside style="..." that are NOT in the allowlist.
    dim_re = re.compile(r'(?<![a-z-])(\d+(?:\.\d+)?)(px|em|rem)(?!["\w])', re.IGNORECASE)
    allowed_values = {"1px", "2px"}
    # CSS properties whose hardcoded values are structurally generated (not design tokens).
    allowed_props = {"min-height", "flex-basis", "width", "height", "max-width"}
    skip_dirs = {"templates/", "parts/", "patterns/"}
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            # Only inspect lines that contain a style= attribute.
            if 'style="' not in line and "style='" not in line:
                continue
            # Extract the style value(s) from the line.
            style_re = re.compile(r'style=["\']([^"\']*)["\']')
            for style_val in style_re.findall(line):
                for m in dim_re.finditer(style_val):
                    full = m.group(0)
                    if full in allowed_values:
                        continue
                    # Identify the CSS property name preceding this value.
                    # segment ends just before the number, so the last ';' delimiter
                    # separates the current declaration from prior ones.
                    segment = style_val[max(0, m.start() - 80):m.start()]
                    last_decl = segment.rsplit(";", 1)[-1]
                    # The declaration is "property:" — take the part before the colon.
                    prop = last_decl.split(":")[0].strip()
                    if any(p in prop for p in allowed_props):
                        continue
                    r.fail(f"{rel}:{lineno}: hardcoded '{full}' in style attribute")
                    break  # one failure per line is enough
    return r


def check_block_attrs_use_tokens() -> Result:
    """Fail if block attribute JSON in templates/parts/patterns uses hardcoded
    layout widths, aspect ratios, or cover heights instead of the SSOT tokens.

    What this catches:
      - "contentSize":"720px"     -> drop the override (use settings.layout.contentSize)
      - "contentSize":"1280px"    -> use "var(--wp--style--global--wide-size)"
      - "contentSize":"<other>px" -> use "var(--wp--custom--layout--<slug>)"
      - "aspectRatio":"4/3"       -> use "var(--wp--custom--aspect-ratio--<slug>)"
      - "minHeight":640           -> drop the attr; set inline style="min-height:var(--wp--custom--cover--<slug>)"

    These all break the "edit one value in theme.json -> ripple everywhere" rule.
    """
    r = Result("Block attributes use design tokens (no hardcoded layout widths, aspect ratios, cover heights)")
    skip_dirs = {"templates/", "parts/", "patterns/"}
    content_size_re = re.compile(r'"contentSize"\s*:\s*"(\d[\w./%]+)"')
    aspect_ratio_re = re.compile(r'"aspectRatio"\s*:\s*"([\d/.]+)"')
    min_height_re = re.compile(r'"minHeight"\s*:\s*\d')
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in content_size_re.finditer(line):
                r.fail(
                    f"{rel}:{lineno}: hardcoded contentSize \"{m.group(1)}\". "
                    f"Drop the override (uses settings.layout.contentSize), or use "
                    f"\"var(--wp--style--global--wide-size)\" / \"var(--wp--custom--layout--<slug>)\"."
                )
            for m in aspect_ratio_re.finditer(line):
                r.fail(
                    f"{rel}:{lineno}: hardcoded aspectRatio \"{m.group(1)}\". "
                    f"Use \"var(--wp--custom--aspect-ratio--<slug>)\"."
                )
            if min_height_re.search(line):
                r.fail(
                    f"{rel}:{lineno}: hardcoded cover minHeight attribute. "
                    f"Remove the attr and set inline style=\"min-height:var(--wp--custom--cover--<slug>)\"."
                )
    return r


def check_no_duplicate_templates() -> Result:
    """Fail if any two files in templates/ have identical content."""
    r = Result("No duplicate template files in templates/")
    import hashlib
    seen: dict[str, str] = {}
    templates_dir = ROOT / "templates"
    if not templates_dir.exists():
        r.fail("templates/ directory missing")
        return r
    for path in sorted(templates_dir.glob("*.html")):
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        rel = path.relative_to(ROOT).as_posix()
        if digest in seen:
            r.fail(f"{rel} is identical to {seen[digest]}")
        else:
            seen[digest] = rel
    if r.passed and not r.skipped:
        r.details.append(f"{len(seen)} templates checked")
    return r


def check_no_ai_fingerprints() -> Result:
    r = Result("No AI-fingerprint vocabulary in user-facing files")
    for name in AI_FINGERPRINT_TARGETS:
        path = ROOT / name
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if AI_FINGERPRINT_RE.search(line):
                r.fail(f"{name}:{lineno}: {line.strip()}")
    return r


def iter_files(suffixes: tuple[str, ...]):
    skip_dirs = {".git", "node_modules", "vendor", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() in suffixes:
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every Obel project check.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip checks that require network (block-name validation against Gutenberg).",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Alias for --offline.",
    )
    args = parser.parse_args()

    offline = args.offline or args.quick

    print(f"Running Obel checks ({'offline' if offline else 'online'})...\n")

    results = [
        check_json_validity(),
        check_php_syntax(),
        check_block_names(offline=offline),
        check_index_in_sync(),
        check_no_important(),
        check_no_stray_css(),
        check_block_prefixes(),
        check_no_ai_fingerprints(),
        check_no_hardcoded_colors(),
        check_no_hardcoded_dimensions(),
        check_block_attrs_use_tokens(),
        check_no_duplicate_templates(),
    ]

    for r in results:
        print(r.render())

    failed = [r for r in results if not r.passed and not r.skipped]
    skipped = [r for r in results if r.skipped]

    print()
    if failed:
        print(f"{RED}FAILED{RESET}: {len(failed)} of {len(results)} checks failed.")
        return 1
    if skipped:
        print(f"{GREEN}OK{RESET}: all checks passed ({len(skipped)} skipped).")
    else:
        print(f"{GREEN}OK{RESET}: all {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
