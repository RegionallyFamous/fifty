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
 11. No raw hex colors in theme.json (outside palette/gradients/duotone)
 12. No remote font URLs (self-hosted Google Fonts only — see AGENTS.md rule 8)
 13. WooCommerce grid integration (clearfix + loop width) safeguards in theme.json
 14. WooCommerce frontend CSS overrides (product tabs etc.) — see AGENTS.md rule 6
 15. Front-page layout differs from every other theme (no "same shape, different
     colors" reskins — see AGENTS.md rule 8)

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, iter_themes, resolve_theme_root  # noqa: E402

# ROOT is set per-theme in main() before any check runs.
ROOT: Path = Path.cwd()

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
    bin_dir = Path(__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, str(bin_dir / "validate-theme-json.py"), str(ROOT / "theme.json")],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        r.fail(proc.stdout.strip() or proc.stderr.strip())
    return r


def check_index_in_sync() -> Result:
    r = Result("INDEX.md in sync (build-index.py --check)")
    bin_dir = Path(__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, str(bin_dir / "build-index.py"), ROOT.name, "--check"],
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


def check_no_hex_in_theme_json() -> Result:
    """Fail if theme.json contains hex colors outside the palette declarations.

    Allowed locations for raw hex: settings.color.palette, settings.color.gradients,
    settings.color.duotone. Anywhere else (styles.css escape hatches,
    settings.shadow.presets, block-level styles, etc.) must use design tokens
    so a single palette edit ripples everywhere.
    """
    r = Result("No raw hex colors in theme.json (outside palette)")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r
    hex_re = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
    allowed_prefixes = (
        "settings.color.palette",
        "settings.color.gradients",
        "settings.color.duotone",
    )

    def walk(node, path: str = "") -> None:
        if any(path.startswith(p) for p in allowed_prefixes):
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            for m in hex_re.finditer(node):
                r.fail(f"theme.json: '{m.group(0)}' at {path}")

    walk(data)
    return r


def check_no_remote_fonts() -> Result:
    """Enforce the self-hosted-Google-Fonts-only rule (AGENTS.md hard rule 8).

    Web fonts MUST be downloaded as .woff2 into assets/fonts/ and registered via
    theme.json `settings.typography.fontFamilies[*].fontFace[*].src` as a
    `file:./assets/fonts/<file>.woff2` path. Any reference to a remote font CDN
    is forbidden — including the Google Fonts CDN. Reasons: privacy, performance,
    license clarity, offline editability.

    Forbidden patterns scanned for:

    1. `theme.json` `fontFace[*].src` containing anything other than `file:` paths
       (`https://`, `http://`, `//cdn`, etc.)
    2. Any string in `theme.json` referencing the known font CDNs
       (fonts.googleapis.com, fonts.gstatic.com, use.typekit.net, fonts.bunny.net,
        fontshare.com, p.typekit.net) — catches `@import` smuggled into
        `styles.css` or per-block `css` escape hatches
    3. Templates / parts / patterns / functions.php / *.php referencing the same
       CDNs (catches `<link rel="preconnect" href="...">`,
       `<link rel="stylesheet" href="...">`, `wp_enqueue_style(..., 'https://fonts...')`)

    System font stacks (`-apple-system`, `BlinkMacSystemFont`, `system-ui`,
    `Helvetica Neue`, `Arial`, `Georgia`, `Iowan Old Style`, etc.) used inside
    `fontFamily` values are always allowed and not scanned.
    """
    r = Result("No remote font URLs (self-hosted Google Fonts only)")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r

    forbidden_hosts = (
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "use.typekit.net",
        "p.typekit.net",
        "fonts.bunny.net",
        "api.fontshare.com",
        "use.fontawesome.com",
    )
    remote_scheme_re = re.compile(r"^(https?:)?//", re.IGNORECASE)

    families = (
        data.get("settings", {})
        .get("typography", {})
        .get("fontFamilies", [])
        or []
    )
    for fam in families:
        if not isinstance(fam, dict):
            continue
        fam_slug = fam.get("slug", "?")
        for face_idx, face in enumerate(fam.get("fontFace", []) or []):
            if not isinstance(face, dict):
                continue
            srcs = face.get("src", [])
            if isinstance(srcs, str):
                srcs = [srcs]
            for src_idx, src in enumerate(srcs or []):
                if not isinstance(src, str):
                    continue
                if remote_scheme_re.search(src):
                    r.fail(
                        f"theme.json: fontFamilies[{fam_slug}].fontFace[{face_idx}].src[{src_idx}]"
                        f" is a remote URL ({src!r}); download the .woff2 to assets/fonts/"
                        f" and use 'file:./assets/fonts/<file>.woff2'."
                    )
                elif not src.startswith("file:"):
                    r.fail(
                        f"theme.json: fontFamilies[{fam_slug}].fontFace[{face_idx}].src[{src_idx}]"
                        f" must start with 'file:./assets/fonts/...' (got {src!r})."
                    )

    def walk_strings(node, path: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk_strings(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk_strings(v, f"{path}[{i}]")
        elif isinstance(node, str):
            lower = node.lower()
            for host in forbidden_hosts:
                if host in lower:
                    r.fail(f"theme.json: '{host}' referenced at {path}")

    walk_strings(data)

    file_targets = []
    for sub in ("templates", "parts", "patterns"):
        sub_path = ROOT / sub
        if sub_path.exists():
            for p in sub_path.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".html", ".php"):
                    file_targets.append(p)
    for php in ROOT.glob("*.php"):
        file_targets.append(php)

    for path in file_targets:
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = text.lower()
        for host in forbidden_hosts:
            if host in lowered:
                for lineno, line in enumerate(text.splitlines(), 1):
                    if host in line.lower():
                        r.fail(f"{rel}:{lineno}: '{host}' — {line.strip()[:120]}")

    return r


def check_wc_grid_integration() -> Result:
    """Catch known WooCommerce + theme.json layout integration bugs.

    Specifically:

    1. CLEARFIX-IN-GRID
       WooCommerce's plugin CSS adds clearfix `::before` and `::after` pseudo-
       elements to `ul.products` (`content:" "; display:table; clear:both`).
       When a theme sets `display:grid` on the same `<ul>`, those pseudos
       become real grid items and consume cells, leaving visible empty slots
       (e.g. 2 product cards on a 4-cell grid show in cells 2 and 3, with
       cells 1 and 4 blank). Fix: in the same scope, hide the pseudos with
       `display:none; content:none;`.

       This check fails if `theme.json` `styles.css` contains a rule that
       sets `display:grid` on a selector ending in `ul.products` (or
       `.products`) and the same scope does not also nullify both
       `::before` and `::after` on that same selector.

    2. WC LOOP WIDTH LEAK
       WC sets `.woocommerce ul.products[class*=columns-] li.product
       { width: 22.05% / 30.79% / 48% / 100% }` based on the `.columns-N`
       class. Inside a grid container those percentages stop the LIs filling
       their cells. Fix: a scoped rule resetting `width:100%` on
       `li.product:nth-child(n)` (the `:nth-child(n)` is needed to win
       specificity over WC's `:nth-child(Nn)` margin-reset rules).

       This check fails if a `display:grid` rule on `ul.products` exists
       without an accompanying `li.product` width reset rule in the same
       theme.json `styles.css`.
    """
    r = Result("WooCommerce grid integration (clearfix + loop width)")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r

    css = ""
    styles = data.get("styles", {})
    if isinstance(styles, dict):
        css = styles.get("css", "") or ""
    if not css:
        return r  # Nothing to check.

    # Find every CSS rule of the form `<selectors> { <body> }`.
    # We deliberately keep this regex simple — theme.json `styles.css` is
    # never deeply nested (no @media, no nesting) by project convention.
    rule_re = re.compile(r"([^{};]+)\{([^{}]*)\}")

    grid_rules: list[tuple[str, str]] = []  # (selectors, body)
    pseudo_rules: list[str] = []             # selector strings
    width_reset_rules: list[str] = []        # selector strings

    for m in rule_re.finditer(css):
        selectors = m.group(1).strip()
        body = m.group(2)
        # Normalize whitespace inside the body for substring checks.
        body_norm = re.sub(r"\s+", "", body)
        sel_list = [s.strip() for s in selectors.split(",")]

        is_grid_on_products = "display:grid" in body_norm and any(
            re.search(r"(?:^|\s|\.)products(?:\s|$)|ul\.products(?:\s|$)", s)
            for s in sel_list
        )
        if is_grid_on_products:
            grid_rules.append((selectors, body_norm))

        is_pseudo_kill = (
            ("display:none" in body_norm or "content:none" in body_norm)
            and any("::before" in s or "::after" in s for s in sel_list)
            and any("ul.products" in s or "products" in s for s in sel_list)
        )
        if is_pseudo_kill:
            pseudo_rules.extend(sel_list)

        is_width_reset = (
            "width:100%" in body_norm
            and any("li.product" in s for s in sel_list)
        )
        if is_width_reset:
            width_reset_rules.extend(sel_list)

    if not grid_rules:
        return r  # No grid on ul.products → nothing to enforce.

    # For each grid rule we found, require both a pseudo-element nullifier
    # and a width-reset rule whose scope overlaps. We use a permissive
    # "scope tag" derived from the selector (.upsells / .related / .shop
    # etc.) so that a grid scoped to .upsells must be paired with pseudo-
    # kills and width-resets that also mention .upsells.
    scope_re = re.compile(r"\.(upsells|related|shop|products|cross-sells|cart-cross-sells)")

    for selectors, _body in grid_rules:
        scopes = set(scope_re.findall(selectors))
        if not scopes:
            scopes = {"products"}

        for scope in scopes:
            has_before = any(
                f".{scope}" in s and "::before" in s for s in pseudo_rules
            )
            has_after = any(
                f".{scope}" in s and "::after" in s for s in pseudo_rules
            )
            has_width_reset = any(
                f".{scope}" in s and "li.product" in s for s in width_reset_rules
            )

            if not (has_before and has_after):
                r.fail(
                    f"grid on `ul.products` scoped to `.{scope}` "
                    "without `::before` AND `::after { display:none; content:none; }` "
                    "in the same scope — WC clearfix pseudos will consume grid cells "
                    f"(rule selectors: {selectors[:120]}{'…' if len(selectors) > 120 else ''})"
                )
            if not has_width_reset:
                r.fail(
                    f"grid on `ul.products` scoped to `.{scope}` "
                    "without `li.product { width:100% }` reset — WC loop widths "
                    "(22%/30%/48%) will leak into grid cells "
                    f"(rule selectors: {selectors[:120]}{'…' if len(selectors) > 120 else ''})"
                )

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


def check_wc_overrides_styled() -> Result:
    """Fail if any WC block known to ship hardcoded frontend CSS lacks a
    `styles.blocks.<block>.css` override that nullifies WC's defaults.

    See AGENTS.md rule 6 (No raw WooCommerce frontend CSS bleeds through).

    Each entry in WC_OVERRIDE_TARGETS lists:
      - the block name,
      - one or more substrings that the `css` field MUST contain (these are
        the WC selectors we are overriding),
      - one or more substrings that MUST appear at least once across the
        full css string (these are the "kill" declarations: `content:none`,
        `border-radius:0`, etc., that prove the WC default has been
        explicitly suppressed rather than left to leak).

    Without these tells, an inherited theme.json may technically have a
    `css` field but still not address the surface (e.g. only setting
    typography/spacing), which is the failure mode that motivated this
    check.
    """
    r = Result("WooCommerce frontend CSS is overridden via theme.json")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r

    blocks = (data.get("styles", {}) or {}).get("blocks", {}) or {}

    WC_OVERRIDE_TARGETS = [
        {
            "block": "woocommerce/product-details",
            "must_target": ["wc-tabs"],
            "must_kill": ["content: none", "content:none"],
            "why": "Product tabs ship as rounded WC 'folder' tabs by default",
        },
    ]

    for target in WC_OVERRIDE_TARGETS:
        block = blocks.get(target["block"])
        css = ""
        if isinstance(block, dict):
            css_field = block.get("css")
            if isinstance(css_field, str):
                css = css_field
        css_norm = re.sub(r"\s+", " ", css)

        if not css:
            r.fail(
                f"`styles.blocks[\"{target['block']}\"]` has no `css` field. "
                f"{target['why']} — add a css override that uses project tokens."
            )
            continue

        if not any(t in css for t in target["must_target"]):
            r.fail(
                f"`styles.blocks[\"{target['block']}\"].css` does not target "
                f"any of {target['must_target']}. WC's default markup will "
                f"render with WC's default styles."
            )
            continue

        if not any(k.replace(" ", "") in css_norm.replace(" ", "")
                   for k in target["must_kill"]):
            r.fail(
                f"`styles.blocks[\"{target['block']}\"].css` does not "
                f"explicitly kill WC's defaults (expected one of "
                f"{target['must_kill']} somewhere in the rule body). "
                f"Without these, WC's `::before`/`::after` shapes leak through."
            )
            continue

        # Specificity bump.
        #
        # WC's `assets/css/woocommerce.css` selectors look like
        # `.woocommerce div.product .woocommerce-tabs ul.tabs li` — that's
        # specificity (0,4,3). The block-prefixed `& .woocommerce-tabs
        # ul.tabs.wc-tabs li` we get by default is (0,4,2), which means WC
        # wins on every shared property (background, padding, float, width,
        # …) and the override only takes effect for properties WC doesn't
        # set. The fix is to prefix every rule with `html body &` so the
        # selector becomes `html body .wp-block-…` ((+0,0,2) = (0,4,4)),
        # mirroring the same trick WC's own `is-style-minimal` rule uses
        # in `client/blocks/assets/js/blocks/product-details/style.scss`.
        #
        # We require the literal substring `html body &` to appear in the
        # css (and any rule that targets a wc-tabs selector to be
        # prefixed with it). A heuristic, but a strict one: it forces the
        # author to make a deliberate decision about specificity.
        rules_targeting_tabs = re.findall(
            r"([^{}]*\.wc-tabs[^{}]*)\{", css
        )
        bare_rules = [
            sel.strip() for sel in rules_targeting_tabs
            if not re.match(r"^\s*html\s+body\s+&", sel.strip())
        ]
        if "html body &" not in css_norm:
            r.fail(
                f"`styles.blocks[\"{target['block']}\"].css` does not use "
                f"the `html body &` specificity-bump prefix. WC's plugin "
                f"CSS targets `.woocommerce div.product .woocommerce-tabs "
                f"ul.tabs li` ((0,4,3)); a bare `& .…` selector is only "
                f"(0,4,2) and loses on every shared property. Prefix every "
                f"rule with `html body &` (the same trick WC's own "
                f"is-style-minimal style uses)."
            )
        elif bare_rules:
            preview = bare_rules[0][:120]
            r.fail(
                f"`styles.blocks[\"{target['block']}\"].css` has at least "
                f"one wc-tabs selector without the `html body &` prefix. "
                f"WC will out-specify it. Offending selector: `{preview}…`"
            )

    if r.passed and not r.skipped:
        r.details.append(f"{len(WC_OVERRIDE_TARGETS)} WC surface(s) checked")
    return r


# Matches a single Gutenberg block delimiter comment:
#   <!-- wp:core/group {"foo":"bar"} -->         opening, attrs
#   <!-- wp:core/group -->                        opening, no attrs
#   <!-- wp:core/spacer {"height":"4px"} /-->     self-closing
#   <!-- /wp:core/group -->                       closing
# Captures: 1 = "/wp:NAME" or "wp:NAME", 2 = JSON attrs (or None), 3 = "/" if self-closing.
_BLOCK_DELIMITER_RE = re.compile(
    r"<!--\s*(/?wp:[a-z][a-z0-9_/-]*)(?:\s+(\{.*?\}))?\s*(/?)-->",
    re.DOTALL,
)


def _front_page_fingerprint(html: str) -> list[str]:
    """Return the structural fingerprint of front-page.html's <main> root.

    The fingerprint is the ordered list of direct children of the
    `<!-- wp:group {"tagName":"main",...} -->` root. Each entry is one of:

        "pattern:slug/name"               — for `wp:pattern` references
        "block-name(first-class-name)"    — when the block carries a className
        "block-name"                      — bare block, no distinguishing class

    Two themes that produce the SAME list have the SAME homepage composition,
    even if every color / font / token underneath differs. That is exactly the
    failure mode the user wants to prevent ("same layout, different colors").

    Empty list = no <main> group found, or no children inside it.
    """
    # Find the opening delimiter of the <main> root group. We can't use a single
    # regex with `[^}]*` here because group attrs routinely embed nested JSON
    # ({"layout":{"type":"constrained"}}). Iterate every wp:group opener and
    # parse its attrs as JSON, picking the first one whose tagName is "main".
    main_open = None
    for m in re.finditer(
        r'<!--\s*wp:group\s+(\{[^>]*?\})\s*-->',
        html,
    ):
        try:
            attrs = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if attrs.get("tagName") == "main":
            main_open = m
            break
    if main_open is None:
        return []

    fingerprint: list[str] = []
    depth = 0
    for tok in _BLOCK_DELIMITER_RE.finditer(html, pos=main_open.end()):
        name = tok.group(1)
        attrs_json = tok.group(2)
        self_closing = tok.group(3) == "/"

        if name.startswith("/wp:"):
            if depth == 0:
                # Closing tag for the <main> group itself — done.
                break
            depth -= 1
            continue

        # Opening (or self-closing) block.
        if depth == 0:
            block = name[len("wp:"):]
            label = block
            if attrs_json:
                try:
                    attrs = json.loads(attrs_json)
                except json.JSONDecodeError:
                    attrs = {}
                if block == "pattern":
                    label = f"pattern:{attrs.get('slug', '?')}"
                else:
                    cls = attrs.get("className", "")
                    first = cls.split()[0] if isinstance(cls, str) and cls else ""
                    if first:
                        label = f"{block}({first})"
            fingerprint.append(label)

        if not self_closing:
            depth += 1

    return fingerprint


def check_front_page_unique_layout() -> Result:
    """Every theme's homepage must be structurally distinct from every other theme's.

    "Different colors and fonts on the same layout" is explicitly disallowed —
    a variant that ships the identical block sequence as obel (or any sibling)
    has not earned its place in the monorepo. Force a real composition.
    """
    r = Result("Front page layout differs from every other theme")
    fp_path = ROOT / "templates" / "front-page.html"
    if not fp_path.exists():
        r.skip("no templates/front-page.html (front page falls through to home/index.html)")
        return r

    my_fp = _front_page_fingerprint(fp_path.read_text(encoding="utf-8"))
    if not my_fp:
        r.fail(
            "templates/front-page.html has no <main> group root, or the root has "
            "no top-level children. Wrap the page in <!-- wp:group "
            '{"tagName":"main", ...} -->.'
        )
        return r

    conflicts: list[tuple[str, list[str]]] = []
    for other in iter_themes():
        if other.resolve() == ROOT.resolve():
            continue
        other_fp_path = other / "templates" / "front-page.html"
        if not other_fp_path.exists():
            continue
        other_fp = _front_page_fingerprint(
            other_fp_path.read_text(encoding="utf-8")
        )
        if other_fp == my_fp:
            conflicts.append((other.name, other_fp))

    if conflicts:
        names = ", ".join(name for name, _ in conflicts)
        r.fail(
            f"templates/front-page.html has the SAME top-level block sequence as "
            f"{names}. A theme variant must do more than reskin colors and fonts: "
            f"the homepage composition itself must differ. Change the section count, "
            f"swap which dynamic surfaces appear (terms-query, product-collection, "
            f"query, media-text, cover, …), reorder them, or introduce a different "
            f"hero pattern.\n"
            f"  this theme: {my_fp}\n"
            f"  {conflicts[0][0]:<11} {conflicts[0][1]}"
        )
    else:
        r.details.append(
            f"{len(my_fp)} top-level section(s); fingerprint unique vs every other theme"
        )
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


def run_checks_for(theme_root: Path, offline: bool) -> int:
    global ROOT
    ROOT = theme_root
    print(f"Running checks for {theme_root.name} ({'offline' if offline else 'online'})...\n")

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
        check_no_hex_in_theme_json(),
        check_no_remote_fonts(),
        check_wc_grid_integration(),
        check_wc_overrides_styled(),
        check_no_hardcoded_dimensions(),
        check_block_attrs_use_tokens(),
        check_no_duplicate_templates(),
        check_front_page_unique_layout(),
    ]

    for r in results:
        print(r.render())

    failed = [r for r in results if not r.passed and not r.skipped]
    skipped = [r for r in results if r.skipped]

    print()
    if failed:
        print(f"{RED}FAILED{RESET}: {len(failed)} of {len(results)} checks failed for {theme_root.name}.")
        return 1
    if skipped:
        print(f"{GREEN}OK{RESET}: all checks passed for {theme_root.name} ({len(skipped)} skipped).")
    else:
        print(f"{GREEN}OK{RESET}: all {len(results)} checks passed for {theme_root.name}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every Fifty project check.")
    parser.add_argument(
        "theme",
        nargs="?",
        default=None,
        help="Theme directory name (e.g. 'obel'). Defaults to cwd if it contains theme.json.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run against every theme in the monorepo.",
    )
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

    if args.all:
        exit_codes = []
        for theme in iter_themes():
            print(f"\n{'=' * 60}")
            exit_codes.append(run_checks_for(theme, offline))
        return 1 if any(exit_codes) else 0

    theme_root = resolve_theme_root(args.theme)
    return run_checks_for(theme_root, offline)


if __name__ == "__main__":
    sys.exit(main())
