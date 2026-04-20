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
    """Fail if any WC surface known to ship hardcoded frontend CSS lacks a
    real override in **top-level** `styles.css`.

    See AGENTS.md rule 6 (No raw WooCommerce frontend CSS bleeds through).

    WHY top-level `styles.css` and not `styles.blocks.<block>.css`:
    WP processes block-scoped css through
    `WP_Theme_JSON::process_blocks_custom_css()`, which wraps every rule in
    `:root :where(<block-selector>) { ... }`. `:where()` has SPECIFICITY
    ZERO, so the *entire* block.css string ends up at `(0,0,1)`. WC's
    plugin CSS sits at `(0,4,3)` (e.g.
    `.woocommerce div.product .woocommerce-tabs ul.tabs li`) — block-scoped
    overrides are silently dwarfed. Top-level `styles.css` is emitted
    verbatim, so we can write the WC selectors with their natural
    specificity and win the cascade by load order (theme after plugin).

    Each entry in WC_OVERRIDE_TARGETS lists:
      - one or more substrings (collapsed of whitespace) the top-level
        styles.css MUST contain — the WC selectors we are overriding,
      - one or more "kill" declarations, at least one of which MUST
        appear, proving WC's defaults (rounded folder corners, pseudo
        shoulders, grey backgrounds) are explicitly suppressed,
      - the block whose `css` field, if present, indicates a stale
        attempt at a block-scoped override that we now treat as a hard
        failure (since it does nothing).
    """
    r = Result("WooCommerce frontend CSS is overridden in styles.css")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r

    styles = (data.get("styles", {}) or {})
    top_css = styles.get("css") if isinstance(styles.get("css"), str) else ""
    top_css_norm = re.sub(r"\s+", "", top_css or "")
    blocks = styles.get("blocks") or {}

    # Each entry locks in one previously-WC-default visual surface. The
    # rules are deliberately narrow: a single brittle selector + a single
    # "kill" declaration that proves we're more than tweaking type — we're
    # actively tearing down WC's chrome (rounded panels, alert bars, star
    # glyphs, etc.). The chunk that satisfies all ten lives in
    # bin/append-wc-overrides.py and was appended to each theme's
    # styles.css; if a future edit strips a selector this list catches it.
    #
    # `must_kill_one_of` strings are matched against `top_css_norm` which
    # has had ALL whitespace stripped (`re.sub(r"\s+", "", ...)`), so the
    # fragments below are intentionally written with no spaces.
    WC_OVERRIDE_TARGETS: list[dict] = [
        {
            "name": "Store notices (F)",
            "must_target": [
                ".woocommerce-message",
                ".woocommerce-error",
                ".woocommerce-info",
                ".added_to_cart",
            ],
            "must_kill_one_of": [
                ".woocommerce-message,.woocommerce-error,.woocommerce-info{border:0;border-radius:0;background:transparent",
            ],
            "inert_block": "woocommerce/store-notices",
            "why": "WC ships green/red alert bars with leading icons. Replace with editorial divider rule (border-top/bottom only).",
        },
        {
            "name": "PDP meta labels (I)",
            "must_target": [
                ".product_meta .sku_wrapper>:first-child",
                ".product_meta .posted_in>:first-child",
                ".product_meta .tagged_as>:first-child",
            ],
            "must_kill_one_of": [
                ".product_meta.sku_wrapper>:first-child,.product_meta.posted_in>:first-child,.product_meta.tagged_as>:first-child{display:none",
            ],
            "why": "WC prefixes meta with literal 'SKU:' / 'Category:' / 'Tags:' labels. Hide the label, keep the value.",
        },
        {
            "name": "Star rating (G)",
            "must_target": [
                ".star-rating",
                ".star-rating>span",
            ],
            "must_kill_one_of": [
                ".star-rating{display:inline-block;position:relative;width:6rem;height:2px",
            ],
            "why": "WC renders 5 gold star glyphs via @font-face. Restyle the same markup as a thin horizontal fill bar.",
        },
        {
            "name": "Variable product form (D)",
            "must_target": [
                "table.variations",
                "table.variations select",
                ".reset_variations",
            ],
            "must_kill_one_of": [
                "table.variationsselect{appearance:none",
            ],
            "why": "WC's <table.variations> is a 2-column grey table with a native browser select. Stack rows + custom chevron + editorial labels.",
        },
        {
            "name": "Lightbox + product gallery (E)",
            "must_target": [
                ".pswp__top-bar",
                ".pswp__button",
                ".pswp__counter",
                ".flex-control-thumbs",
                ".flex-control-thumbs img.flex-active",
            ],
            "must_kill_one_of": [
                ".flex-control-thumbs{display:grid;grid-template-columns:repeat(4,1fr)",
            ],
            "inert_block": "woocommerce/product-image-gallery",
            "why": "PhotoSwipe and the FlexSlider thumbs strip ship with WC's own chrome (round buttons, blue active border).",
        },
        {
            "name": "Mini-cart drawer (C)",
            "must_target": [
                ".wc-block-mini-cart__drawer .components-modal__content",
                ".wc-block-mini-cart-items .wc-block-cart-item",
                ".wc-block-mini-cart__footer",
                ".wc-block-mini-cart__footer-actions",
            ],
            "must_kill_one_of": [
                ".wc-block-mini-cart__drawer.components-modal__content{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--base)",
            ],
            "inert_block": "woocommerce/mini-cart-contents",
            "why": "WC ships a left-aligned drawer with grey panel chrome and a red 'Remove' link. Reskin to editorial panel + pill buttons.",
        },
        {
            "name": "Cart page interior (A)",
            "must_target": [
                ".wc-block-cart",
                ".wc-block-cart-items .wc-block-cart-items__row",
                ".wc-block-components-quantity-selector",
                ".wc-block-cart__sidebar",
                ".wc-block-cart__submit-container",
                ".wc-block-components-totals-coupon__form",
            ],
            "must_kill_one_of": [
                ".wc-block-cart{display:grid;grid-template-columns:1fr",
            ],
            "inert_block": "woocommerce/cart",
            "why": "WC's cart ships rounded blue qty steppers, a panelised 'Cart totals' card, and a green proceed button. Restyle to editorial rows + pill buttons.",
        },
        {
            "name": "Checkout page interior (B)",
            "must_target": [
                ".wc-block-checkout",
                ".wc-block-components-checkout-step",
                ".wc-block-components-checkout-step__title",
                ".wc-block-components-text-input input",
                ".wc-block-components-payment-method",
                ".wc-block-components-checkout-place-order-button",
            ],
            "must_kill_one_of": [
                ".wc-block-checkout{display:grid;grid-template-columns:1fr",
            ],
            "inert_block": "woocommerce/checkout",
            "why": "WC's checkout ships numbered step circles, blue accents on inputs, and a giant green Place-Order button. Restyle to editorial steps + pill buttons.",
        },
        {
            "name": "Order confirmation downloads + create-account (J)",
            "must_target": [
                ".wp-block-woocommerce-order-confirmation-downloads",
                ".wp-block-woocommerce-order-confirmation-downloads table",
                ".wp-block-woocommerce-order-confirmation-create-account form",
            ],
            "must_kill_one_of": [
                ".wp-block-woocommerce-order-confirmation-downloadstable{width:100%;border-collapse:collapse",
            ],
            "why": "WC's downloads block ships a standalone bordered card with a blue Download button. Match the existing summary/totals/addresses treatment.",
        },
        {
            "name": "My Account (K)",
            "must_target": [
                ".woocommerce-account .woocommerce",
                ".woocommerce-MyAccount-navigation",
                ".woocommerce-MyAccount-navigation a",
                ".woocommerce-orders-table",
                ".woocommerce-MyAccount-content",
            ],
            "must_kill_one_of": [
                ".woocommerce-account.woocommerce{display:grid;grid-template-columns:220px1fr",
            ],
            "why": "WC's My Account ships a tab-style sidebar nav and a bordered orders table with WC blue accents. CSS-only restyle to editorial nav + flat tables.",
        },
    ]

    for target in WC_OVERRIDE_TARGETS:
        # 1) Reject any leftover block-scoped `css` field for this surface.
        #    It does nothing (see the docstring) and its presence almost
        #    always means the author thought they had styled the surface
        #    but actually hadn't.
        inert = blocks.get(target["inert_block"]) if target.get("inert_block") else None
        if isinstance(inert, dict) and isinstance(inert.get("css"), str) and inert["css"].strip():
            r.fail(
                f"{target['name']}: found "
                f"`styles.blocks[\"{target['inert_block']}\"].css`, but WP "
                f"wraps that field in `:root :where(...)` (specificity 0,0,1) "
                f"so it cannot beat WC's `(0,4,3)` plugin CSS. Move the WC "
                f"selectors to top-level `styles.css`."
            )
            continue

        # 2) Required selectors must appear (whitespace-insensitive) in the
        #    verbatim top-level styles.css.
        missing = [
            s for s in target["must_target"]
            if re.sub(r"\s+", "", s) not in top_css_norm
        ]
        if missing:
            r.fail(
                f"{target['name']}: top-level `styles.css` is missing "
                f"selector(s) {missing}. {target['why']} Add a rule that "
                f"targets these selectors with theme tokens."
            )
            continue

        # 3) At least one "kill" declaration must appear so we know the
        #    override is doing more than tweaking typography.
        if not any(k in top_css_norm for k in target["must_kill_one_of"]):
            r.fail(
                f"{target['name']}: top-level `styles.css` doesn't kill any "
                f"of WC's defaults (expected one of "
                f"{target['must_kill_one_of']}). Without an explicit reset, "
                f"WC's `::before/::after` shapes and rounded corners leak."
            )
            continue

    if r.passed and not r.skipped:
        if WC_OVERRIDE_TARGETS:
            r.details.append(f"{len(WC_OVERRIDE_TARGETS)} WC surface(s) checked")
        else:
            r.details.append(
                "no WC surfaces currently require a top-level styles.css "
                "override (the tabs surface was retired by "
                "`check_no_wc_tabs_block`)"
            )
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


def check_no_wc_tabs_block() -> Result:
    """Fail if `wp:woocommerce/product-details` is rendered anywhere.

    `woocommerce/product-details` is the umbrella tabs block (Description /
    Additional Information / Reviews) that ships WC's hardcoded rounded
    "folder" tab markup. It is the single biggest "this is a default
    WooCommerce store" tell on a PDP and Baymard's research shows that
    tab-hidden content is ignored by 50%+ of users. We replaced it with a
    description-always-visible composition + native `core/details`
    disclosures (see `single-product.html`).

    This check enforces two things:

    1. No template / part / pattern in this theme references the umbrella
       tabs block (`wp:woocommerce/product-details`). If you need to surface
       a piece of product info, render the relevant individual WC block
       directly (`woocommerce/product-description`, `woocommerce/product-
       reviews`, etc.), wrapped in a `core/details` for collapsible
       sections.

    2. `styles.blocks["woocommerce/product-details"]` is not set in
       `theme.json`. The block is no longer rendered, so any styling there
       is stale config — and historically the surface most likely to drag
       the tabs back into the build by accident.

    See AGENTS.md rule 6.
    """
    r = Result("woocommerce/product-details (tabs block) is not rendered")

    # Part 1: scan templates/parts/patterns for the block delimiter.
    pattern = re.compile(r"<!--\s*wp:woocommerce/product-details(?:\s|/|-->)")
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not (
            rel.startswith("templates/")
            or rel.startswith("parts/")
            or rel.startswith("patterns/")
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                r.fail(
                    f"{rel}:{lineno}: renders `wp:woocommerce/product-details` "
                    f"(the WC tabs block). Replace it with `wp:woocommerce/"
                    f"product-description` for the always-visible description "
                    f"and one `wp:details` per collapsible section "
                    f"(`wp:woocommerce/product-reviews` lives inside one)."
                )

    # Part 2: stale theme.json entry would imply someone is mid-restoration.
    theme_json = ROOT / "theme.json"
    if theme_json.exists():
        try:
            data = json.loads(theme_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        blocks = ((data.get("styles") or {}).get("blocks") or {})
        if "woocommerce/product-details" in blocks:
            r.fail(
                "theme.json still has `styles.blocks[\"woocommerce/product-"
                "details\"]`. The block is no longer rendered — delete the "
                "entry. Style `core/details` instead."
            )

    if r.passed and not r.skipped:
        r.details.append("no WC tabs block in templates/parts/patterns and no stale theme.json styling")
    return r


def check_no_duplicate_stock_indicator() -> Result:
    """Fail if a single-product template renders both
    `wp:woocommerce/product-stock-indicator` AND `wp:woocommerce/add-to-cart-form`
    without a top-level `styles.css` rule that hides the form's native
    `<p class="stock">`.

    Why this exists:
      `wp:woocommerce/add-to-cart-form` is a WC plugin block that echoes the
      add-to-cart `<form>` exactly like the legacy single-product template,
      including `wc_get_stock_html()` → `<p class="stock in-stock">41 in
      stock</p>`. If the template ALSO renders our designed
      `wp:woocommerce/product-stock-indicator` block (which we use to style
      stock copy in the theme's voice — uppercase, tracked, etc.), the
      product page shows "in stock" twice on every PDP. Reviewers consistently
      flag this as the most obvious "default WooCommerce theme" tell on the
      page.

      The fix is a top-level `styles.css` rule that hides the form's
      `<p class="stock">` (and the variation-availability paragraph it shows
      for variable products as the shopper picks attributes). Block-scoped
      `styles.blocks["woocommerce/add-to-cart-form"].css` is NOT enough
      because WP wraps that field in `:root :where(...)` (specificity 0,0,1)
      and WC's stock paragraph CSS hits 0,0,2 — see `check_wc_overrides_styled`
      for the full specificity story.

    What this check enforces, ONLY when the template renders both blocks
    together (i.e. the duplicate is actually possible):

      - Top-level `styles.css` must include selectors that match the form's
        `.stock` element under at least one of: `form.cart` (legacy +
        block-rendered form, the latter inherits `class="cart"`),
        `.wp-block-add-to-cart-form` (the block's outer wrapper),
        `.wc-block-add-to-cart-form__stock` (newer WC versions).
      - It must include a kill declaration (`display:none` or `visibility:hidden`).
      - Variation availability (`.woocommerce-variation-availability`) should
        also be hidden — variable products show a SECOND duplicate "in stock"
        paragraph as the shopper picks attributes if you only hide the form's
        initial one.

    See AGENTS.md rule 6.
    """
    r = Result("No duplicate stock indicator on single-product templates")

    template_paths = [
        ROOT / "templates" / "single-product.html",
        ROOT / "templates" / "single-product-variable.html",
    ]
    template_paths = [p for p in template_paths if p.exists()]
    if not template_paths:
        r.skip("no single-product template found in this theme")
        return r

    needs_hide_rule = False
    triggering_template: Path | None = None
    for path in template_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        renders_indicator = re.search(r"<!--\s*wp:woocommerce/product-stock-indicator(?:\s|/|-->)", text) is not None
        renders_form = re.search(r"<!--\s*wp:woocommerce/add-to-cart-form(?:\s|/|-->)", text) is not None
        if renders_indicator and renders_form:
            needs_hide_rule = True
            triggering_template = path
            break

    if not needs_hide_rule:
        r.skip("template doesn't render both product-stock-indicator and add-to-cart-form")
        return r

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing — cannot verify the stock-hide rule.")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    top_css_norm = re.sub(r"\s+", "", top_css)

    # The hide rule needs both: a selector that matches the form's .stock,
    # and a declaration that suppresses it. Accept any of the three known
    # WC selector roots so this check is robust across WC releases.
    selector_roots = [
        "form.cart.stock",
        ".wp-block-add-to-cart-form.stock",
        ".wc-block-add-to-cart-form__stock",
    ]
    matched_selector = next(
        (sel for sel in selector_roots if sel in top_css_norm),
        None,
    )
    if matched_selector is None:
        r.fail(
            f"{triggering_template.relative_to(ROOT).as_posix()} renders both "
            f"`wp:woocommerce/product-stock-indicator` (designed copy) and "
            f"`wp:woocommerce/add-to-cart-form` (which renders WC's native "
            f"`<p class=\"stock\">` above the quantity input). The result is "
            f"\"in stock\" appearing twice on every PDP. Add a rule to "
            f"top-level `styles.css` matching one of "
            f"{selector_roots} (whitespace ignored) and "
            f"`display:none` so the form's stock paragraph is hidden. The "
            f"recommended selector list is: `form.cart .stock,"
            f".wp-block-add-to-cart-form .stock,"
            f".wc-block-add-to-cart-form__stock,"
            f".woocommerce-variation-availability {{ display: none; }}`. "
            f"Block-scoped `styles.blocks[\"woocommerce/add-to-cart-form\"]"
            f".css` does NOT work — see check_wc_overrides_styled."
        )
        return r

    if "display:none" not in top_css_norm and "visibility:hidden" not in top_css_norm:
        r.fail(
            f"top-level `styles.css` matches `{matched_selector}` but never "
            f"declares `display:none` (or `visibility:hidden`). The form's "
            f"`<p class=\"stock\">` is still visible — duplicating the "
            f"designed product-stock-indicator above."
        )
        return r

    if ".woocommerce-variation-availability" not in top_css_norm:
        r.fail(
            "stock paragraph is hidden, but `.woocommerce-variation-"
            "availability` isn't. On variable products WC renders a SECOND "
            "duplicate `<p class=\"stock\">`-style line under the variation "
            "selector as the shopper picks attributes. Add "
            "`.woocommerce-variation-availability` to the same hide rule."
        )
        return r

    r.details.append(
        f"matched `{matched_selector}` + `display:none` + variation-"
        f"availability hide in top-level styles.css"
    )
    return r


def check_archive_sort_dropdown_styled() -> Result:
    """Fail if a `wp:woocommerce/catalog-sorting` block appears in any archive
    template but the theme never overrides the browser-default `<select>` chrome.

    Why this exists:
      `wp:woocommerce/catalog-sorting` renders a single `<form>` containing a
      bare `<select class="orderby">`. With no theme intervention the browser
      paints its OS-native dropdown — Chevy-grey on macOS, blue on Windows,
      square edges on Linux — directly into an editorial layout. Reviewers
      consistently call this out as the loudest "default WooCommerce theme"
      tell on a shop archive: it breaks the visual rhythm of every adjacent
      typographic element (results count, breadcrumbs, product titles).

      Block-scoped CSS in `styles.blocks["woocommerce/catalog-sorting"].css`
      gets wrapped by WP in `:root :where(.wp-block-woocommerce-catalog-
      sorting)` (specificity 0,0,1) and is overridden by both UA select
      defaults and several WC plugin rules (e.g. `.woocommerce-ordering
      select.orderby` at 0,0,2). Top-level `styles.css` is the only place
      where a rule reliably wins.

      Additionally, `wp:woocommerce/catalog-sorting` is the BLOCK form, but
      the same dropdown is rendered as a legacy `<form class="woocommerce-
      ordering">` on shortcode-driven catalogs (e.g. cart upsell carousel
      templates, `[products]` shortcodes). Selectors must cover both roots
      so a shopper never hits an unstyled native dropdown by accident.

    What this check enforces, ONLY when an archive-style template renders
    the catalog-sorting block (so themes without a shop archive aren't
    forced into rules they don't need):

      - Top-level `styles.css` must include a selector that targets either
        `.wp-block-woocommerce-catalog-sorting select.orderby` or
        `.woocommerce-ordering select.orderby` (whitespace ignored).
      - That rule must declare `appearance:none` (in any of the three
        appearance variants), which is the load-bearing line that strips
        the OS-native chrome and unlocks every other style.
      - Both selector roots should appear, so the legacy non-block render
        also gets the theme's treatment. (Only one selector is REQUIRED for
        the check to pass; missing the second is a warning logged in
        details, not a hard fail — block-only themes still benefit.)

    See AGENTS.md (monorepo) "Shop archive header" rule.
    """
    r = Result("Catalog-sorting <select> styled in top-level styles.css")

    template_paths = sorted(
        (ROOT / "templates").glob("archive-product*.html")
    ) if (ROOT / "templates").exists() else []
    triggering = next(
        (
            p for p in template_paths
            if re.search(r"<!--\s*wp:woocommerce/catalog-sorting(?:\s|/|-->)",
                         p.read_text(encoding="utf-8", errors="replace"))
        ),
        None,
    )
    if triggering is None:
        r.skip("no archive template renders wp:woocommerce/catalog-sorting")
        return r

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing — cannot verify the dropdown override.")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    top_css_norm = re.sub(r"\s+", "", top_css)

    selector_block = ".wp-block-woocommerce-catalog-sortingselect.orderby"
    selector_legacy = ".woocommerce-orderingselect.orderby"
    has_block_sel = selector_block in top_css_norm
    has_legacy_sel = selector_legacy in top_css_norm

    if not (has_block_sel or has_legacy_sel):
        r.fail(
            f"{triggering.relative_to(ROOT).as_posix()} renders "
            f"`wp:woocommerce/catalog-sorting` (a bare `<select "
            f"class=\"orderby\">`) but top-level `styles.css` never "
            f"targets `.wp-block-woocommerce-catalog-sorting select.orderby` "
            f"or `.woocommerce-ordering select.orderby`. Shoppers see the "
            f"OS-native dropdown — the loudest \"default WooCommerce theme\" "
            f"tell on a shop archive. Add a rule like "
            f"`.wp-block-woocommerce-catalog-sorting select.orderby,"
            f".woocommerce-ordering select.orderby {{ appearance:none; "
            f"-webkit-appearance:none; ... }}` to top-level `styles.css`. "
            f"Block-scoped `styles.blocks[\"woocommerce/catalog-sorting\"]"
            f".css` does NOT win against the UA select chrome — see "
            f"check_wc_overrides_styled for the specificity story."
        )
        return r

    if "appearance:none" not in top_css_norm:
        r.fail(
            "top-level `styles.css` matches the catalog-sorting <select> "
            "but never declares `appearance:none`. Without the appearance "
            "reset the browser's native dropdown chrome (chevron, border, "
            "OS focus ring) still paints over your theme styles. Add "
            "`appearance:none;-webkit-appearance:none;-moz-appearance:none` "
            "to the same rule."
        )
        return r

    if not (has_block_sel and has_legacy_sel):
        missing = "legacy `.woocommerce-ordering`" if has_block_sel else "block `.wp-block-woocommerce-catalog-sorting`"
        r.details.append(
            f"WARNING: only one selector root present; consider also "
            f"covering the {missing} root so shortcode-driven catalogs "
            f"render the same dropdown."
        )
    r.details.append(
        f"matched dropdown selector + `appearance:none` in top-level styles.css"
    )
    return r


def check_no_squeezed_wc_sidebars() -> Result:
    """Guard against the WC cart/checkout sidebar-squeeze regression.

    Symptoms (caught in production review on 2026-04-20):
      * Cart page sidebar squeezed to ~200px on tablet/narrow-desktop
        widths -> 'CART TOTALS' wraps to two lines, 'Add coupons'
        wraps to one letter per line, the Proceed-to-Checkout button
        balloons into an oversized pill that overflows the card.
      * Checkout page right column hosting `<order-summary-item>` (a
        nested 64px / 1fr / auto grid) squeezed below ~150px ->
        product names ('Artisanal Silence (8 oz Jar)') and prices wrap
        one glyph per line ('A / r / t / i / s / a / n / a / l').

    Three independent root causes need to all stay fixed for the
    sidebar to render correctly. This rule asserts each one is locked
    in `theme.json` -> top-level `styles.css`:

      1. The original `grid-template-columns:2fr 1fr` shrinks the
         sidebar to below readable width. The fix is
         `grid-template-columns:minmax(0,1fr) minmax(300px,360px)`.
         This rule forbids the bad pattern.

      2. Grid children default to `min-width:auto`, which is the
         intrinsic content width. That defeats `minmax(0, ...)` and
         forces the row to overflow horizontally. Every grid child
         that hosts long-form text inside the sidebar must declare
         `min-width:0`. This rule asserts that for the three
         hot-path selectors.

      3. `word-break:break-all` wraps text on letter boundaries
         instead of word boundaries (it 'fixes' overflow by chopping
         words mid-character). For graceful long-word handling we
         use `overflow-wrap:break-word; word-break:normal` instead.
         This rule forbids `break-all` anywhere in styles.css.

    The CSS that satisfies this lives in
    `bin/append-wc-overrides.py` (`/* wc-tells-cart-sidebar-fix */`
    + `/* wc-tells-checkout-summary-fix */`). If a future edit drops
    a `min-width:0` declaration, re-introduces the `2fr 1fr` grid,
    or sneaks in `word-break:break-all`, this rule fires and the
    bug becomes undeployable.
    """
    r = Result("WC cart/checkout sidebars are not squeeze-prone")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r
    styles = data.get("styles") or {}
    top_css = styles.get("css") if isinstance(styles.get("css"), str) else ""
    css_norm = re.sub(r"\s+", "", top_css or "")

    # 1. Forbid `grid-template-columns:2fr 1fr` for either sidebar parent.
    bad_grids = {
        ".wc-block-cart{grid-template-columns:2fr1fr": ".wc-block-cart",
        ".wc-block-checkout{grid-template-columns:2fr1fr": ".wc-block-checkout",
    }
    for needle, sel in bad_grids.items():
        if needle in css_norm:
            r.fail(
                f"top-level styles.css applies `grid-template-columns: 2fr 1fr` "
                f"to `{sel}`. On tablet widths (~800-1000px) that collapses "
                f"the sidebar to ~200px and triggers per-letter text wrapping. "
                f"Use `minmax(0,1fr) minmax(300px,360px)` instead."
            )

    # 2. Forbid `word-break:break-all` anywhere. It chops words mid-character
    #    when space is tight; we want word-boundary wrapping via
    #    `overflow-wrap:break-word` + `word-break:normal`.
    if "word-break:break-all" in css_norm:
        r.fail(
            "top-level styles.css contains `word-break: break-all`. That wraps "
            "text on letter boundaries (renders 'Artisanal' as 'A r t i s a n "
            "a l' in tight columns). Use `overflow-wrap: break-word; "
            "word-break: normal` instead so wrapping happens on word boundaries."
        )

    # 3. Require `min-width:0` for the three hot-path sidebar grid children.
    #    Heuristic: find every `{...}` body whose preceding selector list
    #    contains the target selector and verify the body declares
    #    `min-width:0`. Multiple appended chunks may target the same
    #    selector in different rules; any one of them counts.
    required_selectors = [
        ".wc-block-cart__sidebar",
        ".wc-block-checkout__sidebar",
        ".wc-block-components-order-summary-item__description",
    ]
    for selector in required_selectors:
        sel_norm = re.sub(r"\s+", "", selector)
        found = False
        idx = 0
        while True:
            i = css_norm.find(sel_norm, idx)
            if i < 0:
                break
            # Walk forward to the rule body for the rule containing this
            # selector occurrence. Only count this selector if it is at the
            # top of its own rule (i.e. the next `{` is the rule body, not
            # a deeper nested at-rule).
            brace_open = css_norm.find("{", i)
            if brace_open < 0:
                break
            brace_close = css_norm.find("}", brace_open)
            if brace_close < 0:
                break
            body = css_norm[brace_open:brace_close]
            if "min-width:0" in body:
                found = True
                break
            idx = brace_close + 1
        if not found:
            r.fail(
                f"top-level styles.css has no rule that targets `{selector}` "
                f"AND declares `min-width:0`. Without this the grid child "
                f"defaults to `min-width:auto` (== intrinsic content width), "
                f"which forces the row to overflow horizontally and triggers "
                f"per-letter text wrapping inside the sidebar. Append a rule "
                f"like `{selector}{{min-width:0}}` to styles.css."
            )

    if r.passed and not r.skipped:
        r.details.append(
            f"checked {len(required_selectors)} sidebar selector(s) for "
            f"`min-width:0`; verified no `word-break:break-all` and no "
            f"`2fr 1fr` grid for cart/checkout"
        )
    return r


def check_blueprint_landing_page() -> Result:
    """Fail if `playground/blueprint.json`'s `landingPage` is anything other
    than `/`.

    Why this matters:
      The repo's docs/<theme>/index.html homepage redirector sends visitors
      to `…&url=/` (because PAGES[0] in bin/_lib.py is `{"slug": "",
      "url": "/", "label": "Home"}`). Playground's `&url=` query param
      overrides `landingPage` from the blueprint, so a stale `landingPage`
      in the JSON wouldn't immediately break the short URL — but it WOULD
      take effect any time someone:

        - Loads the bare blueprint (drag-and-drop, blueprint editor,
          `?blueprint-url=…` with no extra `&url=`),
        - Embeds the blueprint in a third-party launcher,
        - Builds a deep link from `bin/_lib.playground_deeplink(theme,
          "/")` (which omits `&url=` for the home case in some versions).

      Pinning `landingPage` to `/` keeps the blueprint's standalone
      behaviour aligned with the homepage card on demo.regionallyfamous.com
      ("opens the homepage", not "/shop/" or "/wp-admin/"). This check
      exists because the repo's READMEs once silently disagreed with the
      blueprint about which page visitors land on, and the only way to
      catch that is to assert the contract in code.

    See AGENTS.md (monorepo).
    """
    r = Result("Playground blueprint lands on `/`")
    blueprint_path = ROOT / "playground" / "blueprint.json"
    if not blueprint_path.exists():
        r.skip("no playground/blueprint.json (theme without a Playground blueprint)")
        return r
    try:
        data = json.loads(blueprint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"playground/blueprint.json: invalid JSON ({exc}). Cannot validate `landingPage`.")
        return r
    landing = data.get("landingPage")
    if landing is None:
        r.fail(
            "playground/blueprint.json: missing `landingPage`. Set it to "
            "`\"/\"` so the bare blueprint opens the designed homepage "
            "(not WP's default `/wp-admin/` landing). The docs/<theme>/ "
            "redirector forces `&url=/` already, but the blueprint is "
            "consumed standalone too (drag-and-drop, blueprint editor, "
            "third-party launchers)."
        )
    elif landing != "/":
        r.fail(
            f"playground/blueprint.json: `landingPage` is "
            f"`{json.dumps(landing)}`, expected `\"/\"`. The repo's "
            f"homepage card on demo.regionallyfamous.com claims the "
            f"blueprint lands on the home page; keep them in sync. If "
            f"you really do want a different default, update PAGES[0] in "
            f"bin/_lib.py and every README's deeplink table at the same "
            f"time."
        )
    if r.passed and not r.skipped:
        r.details.append("landingPage is `/`")
    return r


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
        check_no_wc_tabs_block(),
        check_no_ai_fingerprints(),
        check_no_hardcoded_colors(),
        check_no_hex_in_theme_json(),
        check_no_remote_fonts(),
        check_wc_grid_integration(),
        check_wc_overrides_styled(),
        check_no_hardcoded_dimensions(),
        check_block_attrs_use_tokens(),
        check_no_duplicate_templates(),
        check_no_duplicate_stock_indicator(),
        check_archive_sort_dropdown_styled(),
        check_no_squeezed_wc_sidebars(),
        check_blueprint_landing_page(),
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
