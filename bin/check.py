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
 16. No unpushed commits on the current branch (a fix isn't "live" until
     `raw.githubusercontent.com` can serve it to the Playground demo)

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
from _lib import MONOREPO_ROOT, iter_themes, resolve_theme_root

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

# Sentinel-bracketed chunks of `theme.json` `styles.css` where `!important`
# is allowed because the cascade fight against WooCommerce plugin CSS is
# unwinnable without it. These are emitted by `bin/append-wc-overrides.py`
# and bracketed by paired `/* <name> */` ... `/* /<name> */` markers.
#
# Adding a chunk to this allow-list is a deliberate decision; do NOT add a
# new entry without:
#   1. trying every selector-specificity workaround first (see
#      `bin/append-wc-overrides.py`'s other chunks for examples that won
#      without `!important`),
#   2. documenting in code WHY the cascade fight cannot be won without it
#      (which exact WC plugin rule + computed specificity beats the theme),
#   3. keeping the chunk as small as humanly possible.
#
# Current entries:
#   * wc-tells-phase-a-premium     -- defends against the legacy
#       woocommerce/product-image-gallery's `opacity:0` start state when
#       its Flexslider/PhotoSwipe JS doesn't init (Playground / fresh-WC
#       failure mode), hides WC blocks loading-skeletons that otherwise
#       flash a blank panel during checkout hydration, and force-fits the
#       variation `<select>`'s font. Without `!important` the WC plugin
#       CSS at `(0,4,3)` wins and the PDP paints empty cream.
#   * wc-tells-phase-c-premium     -- one rule (the WC mini-cart item image
#       sizing for `.wc-block-mini-cart__drawer .wc-block-cart-item__image
#       img, .wc-block-cart-items img`) needs `!important` because WC ships
#       its own width/height on the same selector at the same specificity,
#       and the JS-rendered cart drawer hydrates after our CSS so cascade
#       order doesn't help. Without `!important` cart thumbnails balloon
#       to native image dimensions on first paint.
#   * wc-tells-phase-e-distinctive -- per-theme branded button overrides
#       scoped under `body.theme-<slug>` for `.single_add_to_cart_button`,
#       `.wp-block-button__link`, `.wc-block-components-checkout-place-order-button`,
#       and `.onsale`. WC ships these with property-level `!important` on
#       background/border/padding so the only way for the theme's branded
#       voice to land is to also use `!important`.
IMPORTANT_ALLOWED_SENTINELS = (
    ("/* wc-tells-phase-a-premium */", "/* /wc-tells-phase-a-premium */"),
    ("/* wc-tells-phase-c-premium */", "/* /wc-tells-phase-c-premium */"),
    ("/* wc-tells-phase-e-distinctive */", "/* /wc-tells-phase-e-distinctive */"),
    # Phase J — Aero iridescent voice. Uses !important to win over the
    # cloned-from-obel Phase E rules with `body.theme-aero` selectors that
    # would otherwise paint Aero with Obel's hairline-square voice. The
    # entire chunk is body.theme-aero scoped so it's inert on every other
    # theme.
    ("/* wc-tells-phase-j-aero-iridescent */", "/* /wc-tells-phase-j-aero-iridescent */"),
    # Phase M -- a11y contrast tweaks for upstream-WC component states.
    # Uses !important to win over WC Blocks' own component CSS for the
    # disabled add-to-cart button, the comment-reply-link accent paint,
    # and the `.is-disabled` cart-item loading flash. The whole chunk is
    # documented inline in `bin/append-wc-overrides.py` (PHASE_M block).
    ("/* wc-tells-phase-m-a11y-contrast */", "/* /wc-tells-phase-m-a11y-contrast */"),
)


# ----------------------------------------------------------------------
# Sentinel-bracketed regions of styles.css where raw hex literals are
# allowed by `check_no_hex_in_theme_json`. Same shape and same
# justification as `IMPORTANT_ALLOWED_SENTINELS`: distinctive chrome
# chunks that paint multi-stop gradients (iridescent buttons, y2k
# aurora backgrounds, frosted-glass cards) need precise color stops
# that don't have palette equivalents. Bloating the palette with one
# token per gradient stop ("aurora-stop-1", "shine-stop-2", ...)
# makes the palette useless as a design surface, so the explicit
# allow-list is "yes, this hex is intentional, it's part of a
# multi-stop gradient or a `text-shadow` rgba — not a stray brand
# color that should have been a palette token". Each entry MUST
# cover a chunk that is theme-scoped (`body.theme-<slug>`) so the
# raw hex can't leak into other themes' computed style.
HEX_ALLOWED_SENTINELS = (
    (
        "/* wc-tells-phase-j-aero-iridescent */",
        "/* /wc-tells-phase-j-aero-iridescent */",
    ),
)


def _strip_allowed_hex_chunks(text: str) -> str:
    """Same shape as `_strip_allowed_important_chunks`, but for the
    raw-hex scan inside `theme.json`'s `styles.css` string. Operates
    on the raw string (NOT line-by-line) because
    `bin/append-wc-overrides.py` emits each chunk as one minified
    line (sentinels and rules glued together).
    """
    out = text
    for open_marker, close_marker in HEX_ALLOWED_SENTINELS:
        while True:
            i = out.find(open_marker)
            if i == -1:
                break
            j = out.find(close_marker, i + len(open_marker))
            if j == -1:
                break
            out = out[:i] + out[j + len(close_marker) :]
    return out


def _strip_allowed_important_chunks(text: str) -> str:
    """Remove sentinel-bracketed regions from `text` so the `!important`
    scan can ignore them. Operates on the raw string (NOT line-by-line)
    because `bin/append-wc-overrides.py` emits the chunks as one minified
    line each, so the open + close sentinels usually live on the same
    line as the rules between them.
    """
    out = text
    for open_marker, close_marker in IMPORTANT_ALLOWED_SENTINELS:
        while True:
            i = out.find(open_marker)
            if i == -1:
                break
            j = out.find(close_marker, i + len(open_marker))
            if j == -1:
                # Unclosed marker -- bail out, leave the rest untouched so
                # the scan still catches new !important rules added past
                # the dangling sentinel.
                break
            out = out[:i] + out[j + len(close_marker) :]
    return out


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
        scanned = _strip_allowed_important_chunks(text)
        for lineno, line in enumerate(scanned.splitlines(), 1):
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
        if not (
            rel.startswith("templates/") or rel.startswith("parts/") or rel.startswith("patterns/")
        ):
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
            scanned = _strip_allowed_hex_chunks(node) if path.endswith("styles.css") else node
            for m in hex_re.finditer(scanned):
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

    families = data.get("settings", {}).get("typography", {}).get("fontFamilies", []) or []
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
    pseudo_rules: list[str] = []  # selector strings
    width_reset_rules: list[str] = []  # selector strings

    for m in rule_re.finditer(css):
        selectors = m.group(1).strip()
        body = m.group(2)
        # Normalize whitespace inside the body for substring checks.
        body_norm = re.sub(r"\s+", "", body)
        sel_list = [s.strip() for s in selectors.split(",")]

        is_grid_on_products = "display:grid" in body_norm and any(
            re.search(r"(?:^|\s|\.)products(?:\s|$)|ul\.products(?:\s|$)", s) for s in sel_list
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

        is_width_reset = "width:100%" in body_norm and any("li.product" in s for s in sel_list)
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
            has_before = any(f".{scope}" in s and "::before" in s for s in pseudo_rules)
            has_after = any(f".{scope}" in s and "::after" in s for s in pseudo_rules)
            has_width_reset = any(f".{scope}" in s and "li.product" in s for s in width_reset_rules)

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
                    segment = style_val[max(0, m.start() - 80) : m.start()]
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
    layout widths or aspect ratios instead of the SSOT tokens.

    What this catches:
      - "contentSize":"720px"     -> drop the override (use settings.layout.contentSize)
      - "contentSize":"1280px"    -> use "var(--wp--style--global--wide-size)"
      - "contentSize":"<other>px" -> use "var(--wp--custom--layout--<slug>)"
      - "aspectRatio":"4/3"       -> use "var(--wp--custom--aspect-ratio--<slug>)"

    These all break the "edit one value in theme.json -> ripple everywhere" rule.

    NOTE: cover `minHeight` is intentionally NOT checked here. The cover block's
    save() function reads `minHeight` + `minHeightUnit` from the JSON attrs and
    emits the inline `min-height` itself; using a CSS-var-only inline style with
    no JSON attr produces invalid block markup that the editor silently rewrites
    on load (caught by `bin/blocks-validator/`).
    """
    r = Result("Block attributes use design tokens (no hardcoded layout widths, aspect ratios)")
    skip_dirs = {"templates/", "parts/", "patterns/"}
    content_size_re = re.compile(r'"contentSize"\s*:\s*"(\d[\w./%]+)"')
    aspect_ratio_re = re.compile(r'"aspectRatio"\s*:\s*"([\d/.]+)"')
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in content_size_re.finditer(line):
                r.fail(
                    f'{rel}:{lineno}: hardcoded contentSize "{m.group(1)}". '
                    f"Drop the override (uses settings.layout.contentSize), or use "
                    f'"var(--wp--style--global--wide-size)" / "var(--wp--custom--layout--<slug>)".'
                )
            for m in aspect_ratio_re.finditer(line):
                r.fail(
                    f'{rel}:{lineno}: hardcoded aspectRatio "{m.group(1)}". '
                    f'Use "var(--wp--custom--aspect-ratio--<slug>)".'
                )
    return r


def check_block_markup_anti_patterns() -> Result:
    """Fail if any pattern/template/part contains a known block-markup anti-pattern
    that the WordPress editor will flag as 'invalid content' (or silently auto-
    upgrade on load).

    These are the cheap-to-detect invariants. The expensive editor-parity diff
    lives in `bin/blocks-validator/check-blocks.mjs` (run via
    `check_blocks_validator()` below); this function exists so that a typical
    edit gets quick feedback without requiring Node.js.

    Invariants enforced (one fail line per offender):
      1. core/group: when the JSON declares `border.color` (preset or raw),
         the rendered <div> MUST carry the `has-border-color` class. Save()
         emits it and the validator rejects the block otherwise.
      2. core/paragraph: the class list MUST NOT include legacy
         `wo-empty__*` markers -- core/paragraph doesn't support a custom
         className via that selector and save() drops them, breaking the
         round-trip.
      3. core/button: `box-shadow` belongs on the inner `<a class=
         "wp-block-button__link wp-element-button">`, NEVER on the outer
         `<div class="wp-block-button">`. Save() places it on the link.
      4. core/accordion: the wrapper `<div class="wp-block-accordion">`
         MUST carry `role="group"`. Save() emits it; the editor silently
         rewrites the markup on first load if it's missing, which means
         the next edit-and-save round-trip will produce a noisy diff.
         Caught by `@wordpress/block-library` 9.44+; we lint it here so
         contributors don't need to wait for the Node validator.
      5. <button> in patterns/templates/parts MUST declare an explicit
         `type=` attribute. Without it, the HTML default is `submit`,
         which inside any `<form>` (cart, checkout, mini-cart) silently
         submits the form on click. Belt-and-braces against the editor
         silently injecting `type="button"` on save() and the next
         round-trip looking like a "fix" in CI.
      6. core/heading: when the JSON declares `fontSize` (top-level
         shortcut) or `style.typography.{fontFamily,fontWeight,fontStyle,
         letterSpacing,lineHeight,textTransform,fontSize}`, the rendered
         `<h*>` tag MUST carry the matching `has-<slug>-font-size` /
         `has-<slug>-font-family` class and the matching CSS property
         in its inline `style` attribute. Without the class/style, the
         editor's `parse()` falls through to the deprecation pipeline
         which silently rescues the markup at editor load -- but the
         FRONT-END serves the bare markup, so the heading falls through
         to `styles.elements.h2.fontSize` defaults (typically 4-7.5rem
         display sizes) and renders nothing like the design intent.
         This is the exact regression that shipped chunky 100px display
         headings in the aero/lysholm/selvedge footers; fast-path here
         so future generators can't recreate it without tripping the
         pre-commit hook in <0.1s.
      7. core/post-template: when `layout.type == "grid"`, the JSON
         MUST set EITHER `columnCount` (fixed N columns: produces
         `repeat(N, minmax(0, 1fr))`) OR `minimumColumnWidth` (responsive:
         produces `repeat(auto-fill, minmax(<width>, 1fr))`), NEVER
         both. With both set, WordPress picks the `auto-fill` algorithm
         and ignores `columnCount`, so a `{"columnCount":3,
         "minimumColumnWidth":"18rem"}` on a 1280px wide-size container
         renders as 4-5 column tracks with only 3 populated -- cards
         compress to the minimum width and a void appears beside them.
         This is the exact regression that shipped a "From the
         Workbench" section with cards squished into 60% of the width
         in selvedge/aero/lysholm/obel front-pages. Fast-path here so
         future generators can't recreate it.
    """
    r = Result(
        "Block markup matches save() output "
        "(group classes, button shadow, paragraph classes, accordion role, button type, heading typography, post-template grid)"
    )

    skip_dirs = {"templates/", "parts/", "patterns/"}
    files: list[Path] = []
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        files.append(path)

    # --- Invariant 1: core/group with border.color preset must add has-border-color
    group_open_re = re.compile(
        r'<!--\s*wp:group\s+(\{[^>]*?\})\s*-->\s*\n\s*(<(?:div|main|section|aside|nav|header|footer|article|figure)\s+[^>]*class="[^"]*?wp-block-group[^"]*?"[^>]*>)'
    )

    # --- Invariant 3: core/button shadow on outer wrapper
    button_outer_shadow_re = re.compile(
        r'<div\s+class="wp-block-button[^"]*"[^>]*style="[^"]*box-shadow:'
    )

    # NB: We deliberately do NOT lint `woocommerce/product-price` for self-close
    # form. The block ships both render paths and the editor-parity validator
    # stubs WC blocks anyway -- the regex is too coarse to disambiguate
    # standalone uses from query-loop descendants reliably.

    # NB: We deliberately do NOT lint `core/quote` for a JSON `citation` attribute.
    # Save() preserves the inner `<cite>` element inside `<blockquote>` verbatim,
    # so the editor-parity validator round-trips both forms cleanly.

    # NB: We deliberately do NOT lint `core/heading` for a `content` attribute
    # in JSON. Save() round-trips it cleanly when it matches the inner HTML
    # (verified by the editor-parity validator across 2700+ blocks), and a
    # naive regex check produces a flood of false positives.

    # --- Invariant 2: core/paragraph anti-patterns
    para_block_re = re.compile(
        r"<!--\s*wp:paragraph\s+(\{[^>]*?\})\s*-->\s*\n\s*(<p\s+[^>]*>)",
        re.MULTILINE,
    )

    # --- Invariant 4: core/accordion wrapper requires role="group".
    # Match `<!-- wp:accordion ... -->` followed by the next block-element
    # opener whose class list contains `wp-block-accordion` (but NOT one of
    # the child variants like `wp-block-accordion-item`). Allow attribute
    # noise before the class= so themes can add anchor IDs etc.
    accordion_open_re = re.compile(
        r"<!--\s*wp:accordion(?:\s+\{[^}]*\})?\s*-->\s*\n\s*"
        r'(<(?:div|section)\s+[^>]*class="[^"]*\bwp-block-accordion(?!-)[^"]*"[^>]*>)'
    )

    # --- Invariant 5: <button> tags must declare an explicit `type=`.
    # Lookahead: any opening `<button` not immediately followed (within the
    # tag) by a `type=` attribute. We anchor on `<button` followed by either
    # whitespace+attrs or `>`; the `(?![^>]*\stype=)` ensures no `type=`
    # appears before the closing `>`. Self-closing variants are not used in
    # block markup, so we don't bother matching them.
    button_no_type_re = re.compile(r"<button(?![^>]*\stype=)(?:\s[^>]*)?>")

    # --- Invariant 6: core/heading typography JSON ↔ markup coherence.
    # Match `<!-- wp:heading {...} -->` followed by an `<h1>`–`<h6>` tag.
    # We do not anchor on a newline-only join because some patterns put
    # the opening comment and the tag on the same line.
    heading_block_re = re.compile(
        r"<!--\s*wp:heading\s+(\{[^>]*?\})\s*-->\s*\n?\s*(<h[1-6]\b[^>]*>)",
        re.MULTILINE,
    )
    # Map JSON style.typography.<key> → CSS property. Keep `fontSize` last
    # so the message is consistent with how save() orders the inline style.
    HEADING_TYPO_PROPS = (
        ("fontFamily", "font-family"),
        ("fontStyle", "font-style"),
        ("fontWeight", "font-weight"),
        ("fontSize", "font-size"),
        ("letterSpacing", "letter-spacing"),
        ("lineHeight", "line-height"),
        ("textTransform", "text-transform"),
    )

    # --- Invariant 7: core/post-template grid layout must pick ONE
    # column-sizing algorithm. We match `<!-- wp:post-template {...} -->`
    # and inspect the JSON for the layout block + the two column-sizing
    # keys; the failure logic lives in the per-file loop so the line
    # number is right.
    post_template_re = re.compile(
        r"<!--\s*wp:post-template\s+(\{[^>]*?\})\s*-->",
        re.MULTILINE,
    )

    def _slug_to_class_token(slug: str) -> str:
        """Mirror @wordpress/blocks save()'s slug → kebab-case conversion.
        WP inserts a hyphen at every digit↔letter boundary so a JSON
        `fontSize:"4xl"` (or `"4-xl"`) becomes `has-4-xl-font-size` in
        the rendered class list. Without this normalisation the check
        false-positives on every numeric size preset.
        """
        # digit followed by letter, or letter followed by digit
        s = re.sub(r"(\d)([A-Za-z])", r"\1-\2", slug)
        s = re.sub(r"([A-Za-z])(\d)", r"\1-\2", s)
        # collapse any accidental double hyphens (slug already had a `-`)
        return re.sub(r"-+", "-", s)

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        # Invariant 1: group + top-level border.color + has-border-color.
        # Save() only emits `has-border-color` when border.color is set as a
        # single string at the top level of `border`. Per-side borders
        # (`border.top.color`, etc.) are styled inline and do NOT add the class.
        for m in group_open_re.finditer(text):
            json_part, tag = m.group(1), m.group(2)
            if not re.search(r'"border"\s*:\s*\{[^{}]*?"color"\s*:\s*"', json_part):
                continue
            if "has-border-color" in tag:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/group declares border.color but rendered <{tag.split()[0][1:]}> "
                f"is missing the `has-border-color` class. Add it to the class list."
            )

        # Invariant 2: paragraph legacy wo-empty__ class.
        # core/paragraph save() drops unknown classes from the rendered
        # class list UNLESS they were declared in the `className` block
        # attribute -- the editor uses that attribute as the canonical
        # custom class store and re-emits it on every save. So a
        # `wp:paragraph {"className":"wo-empty__eyebrow"}` keeps the
        # class on round-trip (the cart-page.php pattern relies on this
        # for empty-cart-block CSS hooks); only raw classes injected
        # straight into the `<p>` tag without a matching className attr
        # get silently scrubbed by the editor.
        for m in para_block_re.finditer(text):
            json_part, tag = m.group(1), m.group(2)
            if "wo-empty__" not in tag:
                continue
            classname_attr = re.search(r'"className"\s*:\s*"([^"]*)"', json_part)
            preserved = set()
            if classname_attr:
                preserved = {c for c in classname_attr.group(1).split() if c}
            tag_classes = re.search(r'\sclass="([^"]*)"', tag)
            tag_class_set = set(tag_classes.group(1).split()) if tag_classes else set()
            unsupported = {
                c for c in tag_class_set if c.startswith("wo-empty__") and c not in preserved
            }
            if not unsupported:
                continue
            lineno = text.count("\n", 0, m.start(2)) + 1
            r.fail(
                f"{rel}:{lineno}: core/paragraph carries legacy `wo-empty__*` "
                f"class(es) {sorted(unsupported)} that are NOT mirrored in "
                f"the block's `className` attribute. core/paragraph save() "
                f"only preserves classes declared via `className`; raw "
                f"classes inlined into `<p>` are dropped on the next editor "
                f'round-trip. Add them to `"className":"..."` in the '
                f"`wp:paragraph` JSON, or remove them."
            )

        # Invariant 3: button shadow on outer wrapper
        for m in button_outer_shadow_re.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/button has `box-shadow` on the outer "
                f"`.wp-block-button` div. Move it to the inner `a.wp-block-button__link` -- "
                f"that's where save() places it."
            )

        # Invariant 4: accordion wrapper must declare role="group".
        for m in accordion_open_re.finditer(text):
            tag = m.group(1)
            if re.search(r'\brole\s*=\s*"group"', tag):
                continue
            lineno = text.count("\n", 0, m.start(1)) + 1
            r.fail(
                f'{rel}:{lineno}: core/accordion wrapper is missing `role="group"`. '
                f"Save() emits it; without it the editor will silently rewrite the "
                f"markup on first load and the next round-trip will look like a regression."
            )

        # Invariant 5: any <button> in pattern/template/part markup must
        # carry an explicit `type=` attribute. Default-`submit` buttons
        # inside the cart, mini-cart, and checkout forms detonate on click.
        for m in button_no_type_re.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: <button> is missing an explicit `type=` attribute. "
                f'Add `type="button"` (or `type="submit"` if it really is a form '
                f"submit) -- the HTML default is `submit`, which silently posts any "
                f"surrounding <form> on click."
            )

        # Invariant 6: core/heading typography JSON ↔ markup coherence.
        for m in heading_block_re.finditer(text):
            json_part, tag = m.group(1), m.group(2)
            tag_classes_m = re.search(r'\sclass\s*=\s*"([^"]*)"', tag)
            tag_classes = set(tag_classes_m.group(1).split()) if tag_classes_m else set()
            tag_style_m = re.search(r'\sstyle\s*=\s*"([^"]*)"', tag)
            tag_style = tag_style_m.group(1) if tag_style_m else ""
            tag_style_props = {
                p.split(":", 1)[0].strip().lower()
                for p in tag_style.split(";")
                if ":" in p
            }
            missing: list[str] = []

            # 6a. Top-level `fontSize: "<slug>"` shortcut → has-<kebab-slug>-font-size class.
            font_size_short = re.search(
                r'(?<![\w])"fontSize"\s*:\s*"([A-Za-z0-9_-]+)"', json_part
            )
            if font_size_short and not re.search(
                r'(?<![\w])"style"\s*:\s*\{[^{}]*?"typography"\s*:\s*\{[^{}]*?"fontSize"',
                json_part,
            ):
                slug = font_size_short.group(1)
                expected = f"has-{_slug_to_class_token(slug)}-font-size"
                if expected not in tag_classes:
                    missing.append(f"class `{expected}` (from JSON fontSize:\"{slug}\")")

            # 6b. Top-level `fontFamily: "<slug>"` shortcut → has-<kebab-slug>-font-family class.
            # Skip values that look like CSS variables / preset references --
            # those go in `style.typography.fontFamily`, not the shortcut.
            font_family_short = re.search(
                r'(?<![\w])"fontFamily"\s*:\s*"([A-Za-z0-9_-]+)"', json_part
            )
            if font_family_short:
                slug = font_family_short.group(1)
                expected = f"has-{_slug_to_class_token(slug)}-font-family"
                if expected not in tag_classes:
                    missing.append(f"class `{expected}` (from JSON fontFamily:\"{slug}\")")

            # 6c. style.typography.<prop> → matching CSS property in inline style.
            typo_block = re.search(
                r'"style"\s*:\s*\{[^{}]*?"typography"\s*:\s*(\{[^{}]*?\})',
                json_part,
            )
            if typo_block:
                typo_json = typo_block.group(1)
                for json_key, css_prop in HEADING_TYPO_PROPS:
                    if not re.search(rf'(?<![\w])"{json_key}"\s*:\s*"', typo_json):
                        continue
                    if css_prop not in tag_style_props:
                        missing.append(
                            f"inline `style` property `{css_prop}` "
                            f"(from JSON style.typography.{json_key})"
                        )

            if missing:
                lineno = text.count("\n", 0, m.start(2)) + 1
                tag_name = re.match(r"<(h[1-6])", tag).group(1)
                r.fail(
                    f"{rel}:{lineno}: core/heading <{tag_name}> is missing "
                    f"{len(missing)} attribute(s) the JSON declared: "
                    + "; ".join(missing)
                    + ". Without these, the front-end serves bare markup that "
                    + f"falls through to `styles.elements.{tag_name}` defaults "
                    + "(typically display-size headings). The editor's deprecation "
                    + "pipeline silently rewrites the markup on load so the bug "
                    + "only surfaces in production. Mirror the JSON into the "
                    + "rendered tag (add the class(es) and the inline style "
                    + "properties shown above)."
                )

        # Invariant 7: post-template grid layout must pick ONE sizing algo.
        for m in post_template_re.finditer(text):
            json_part = m.group(1)
            # Only evaluate when layout.type is grid; flex / stack templates
            # don't use these keys.
            if not re.search(r'"layout"\s*:\s*\{[^{}]*?"type"\s*:\s*"grid"', json_part):
                continue
            has_column_count = bool(
                re.search(r'(?<![\w])"columnCount"\s*:\s*\d+', json_part)
            )
            # `minimumColumnWidth` is "set" only when its value is a non-empty
            # string. `null` and `""` mean "unset" -- the canonical pattern
            # used by every working post-template in this repo.
            min_col_width = re.search(
                r'(?<![\w])"minimumColumnWidth"\s*:\s*"([^"]+)"', json_part
            )
            if has_column_count and min_col_width:
                lineno = text.count("\n", 0, m.start()) + 1
                r.fail(
                    f"{rel}:{lineno}: core/post-template has BOTH `columnCount` "
                    f"and `minimumColumnWidth: \"{min_col_width.group(1)}\"`. "
                    f"WordPress's grid layout picks the `auto-fill` algorithm "
                    f"when `minimumColumnWidth` is set and ignores `columnCount`, "
                    f"so the rendered grid creates as many tracks as fit at the "
                    f"minimum width -- only the first N populate, leaving an "
                    f"empty void beside them at wide viewports. Pick one: set "
                    f"`\"minimumColumnWidth\":null` for fixed N columns, or "
                    f"drop `columnCount` for a responsive grid. The canonical "
                    f"pattern across this repo is `\"columnCount\":N,"
                    f"\"minimumColumnWidth\":null`."
                )

    if r.passed:
        r.details.append(f"{len(files)} pattern/template/part file(s) checked")
    return r


def check_blocks_validator() -> Result:
    """Run the Node.js editor-parity validator (`bin/blocks-validator/`) and
    surface any block that the WP editor would flag or auto-upgrade on load.

    This is the canonical answer to "would the editor accept this markup?".
    The Python anti-pattern check above catches the cheap stuff fast; this
    one boots @wordpress/blocks under JSDOM and runs the real `parse()` +
    `validateBlock()` pipeline, so it finds the long tail (subtle class
    ordering, deprecated attribute shapes, etc.) too.

    Skipped (not failed) if Node.js or the validator's `node_modules/` are
    missing -- the contributor doc explains how to set them up.
    """
    r = Result("Block markup passes the @wordpress/blocks editor-parity validator")
    if shutil.which("node") is None:
        r.skip("`node` not on PATH; install Node 18+ to run editor-parity validation.")
        return r
    validator_dir = MONOREPO_ROOT / "bin" / "blocks-validator"
    if not (validator_dir / "node_modules").exists():
        r.skip(
            f"`{validator_dir}/node_modules/` missing. "
            f"Run `cd {validator_dir} && npm install` once to enable this check."
        )
        return r
    script = validator_dir / "check-blocks.mjs"
    try:
        proc = subprocess.run(
            ["node", str(script), str(ROOT)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        r.fail("blocks-validator timed out after 120s")
        return r
    if proc.returncode == 0:
        # Last line is the summary, e.g. "✓ Validated 569 blocks across 45 file(s) ..."
        last = (proc.stderr.strip().splitlines() or [""])[-1]
        if last:
            r.details.append(last)
        return r
    # Non-zero exit: extract the per-block headers ("─── core/group in <file>") and
    # surface them as fail lines. The full diff stays in stderr for debugging but
    # would drown the summary table.
    headers = [line.strip() for line in proc.stderr.splitlines() if line.startswith("─── ")]
    if not headers:
        # Surface the raw stderr if we can't parse it.
        r.fail(proc.stderr.strip()[:1000])
        return r
    for h in headers:
        # Strip the leading "─── " for the fail-line format.
        r.fail(h[4:])
    return r


def check_no_fake_forms() -> Result:
    """Fail if any pattern/template/part contains a 'form-shaped' block that
    cannot actually submit anywhere.

    WordPress core ships **no** working email-capture or newsletter form
    block. The only form-ish blocks in core are:

      * `core/search`             -- submits `?s=…` to the home URL.
      * `core/login`              -- submits to `wp-login.php`.
      * `core/comments` (and kin) -- per-post comment form.

    Project history is full of "newsletter signup" patterns built out of
    `core/search` styled to look like an email field, or `core/html`
    blocks containing a raw `<form action="/?wo-newsletter=1">`. They
    look real but submit to nothing -- a visitor who types their email
    and clicks the button gets either a search-results page for their
    own address or a 404. That's worse than no form at all.

    The hard rule against non-`core/*` / non-`woocommerce/*` blocks
    (AGENTS.md rule #4) makes a real email-capture form impossible
    inside this codebase, so the only honest path is to ban the fake
    ones. Replace newsletter sections with something that actually
    works: `woocommerce/customer-account`, a link to a real journal /
    page, a `core/social-links` cluster, a featured `woocommerce/
    product-collection`, etc.

    Two surfaces are checked:

      1. `core/search` is allowed ONLY in genuinely-search contexts:
         `parts/header.html`, `parts/no-results.html`,
         `templates/search.html`, `templates/product-search-results.html`,
         and `templates/404.html` (where a search prompt makes sense
         when the URL was wrong). Anywhere else it's a fake form.

      2. `core/html` blocks are scanned for `<form`,
         `<input type="email"`, or a Subscribe / Sign up / Notify-me
         button. Any of those is a fake submission target.

    Fix path: pick a real action -- `woocommerce/customer-account`,
    a `<a>` to `/my-account/`, `/journal/`, `/contact/`, a featured
    collection -- and route the user there instead.
    """
    r = Result("No fake forms (no email-capture stand-ins built out of core/search or raw <form>)")

    search_allowed_paths = {
        "parts/header.html",
        "parts/no-results.html",
        "templates/search.html",
        "templates/product-search-results.html",
        "templates/404.html",
    }
    skip_dirs = ("templates/", "parts/", "patterns/")

    files: list[Path] = []
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in skip_dirs):
            files.append(path)

    search_re = re.compile(r"<!--\s*wp:search\b")
    html_block_re = re.compile(
        r"<!--\s*wp:html\s*-->\s*(.*?)\s*<!--\s*/wp:html\s*-->",
        re.DOTALL,
    )
    fake_form_signals = re.compile(
        r"<form\b|<input[^>]*type=[\"']email[\"']|<button[^>]*>\s*(?:subscribe|sign\s*up|notify|join the list)\b",
        re.IGNORECASE,
    )

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        for m in search_re.finditer(text):
            if rel in search_allowed_paths:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/search outside a real search surface. "
                f"This block submits `?s=…` to the home URL -- it can't capture "
                f"emails or subscriptions. Replace with a real CTA "
                f"(woocommerce/customer-account, an <a> to /my-account/ or "
                f"/journal/, a core/social-links cluster, etc.)."
            )

        for m in html_block_re.finditer(text):
            body = m.group(1)
            sig = fake_form_signals.search(body)
            if not sig:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/html block contains a raw <form> or "
                f"email-capture markup ('{sig.group(0)[:40]}') that submits to "
                f"nothing real. Replace with a working CTA -- a real <a> to "
                f"/my-account/, a woocommerce/customer-account block, or "
                f"core/social-links."
            )

    if r.passed:
        r.details.append(f"{len(files)} pattern/template/part file(s) scanned for fake forms")
    return r


def check_no_empty_cover_blocks() -> Result:
    """Fail if any pattern/template/part contains a `wp:cover` whose `url`
    is empty/missing AND `dimRatio` is below 30 -- i.e., a cover that
    paints nothing at all.

    Why this exists:
      `wp:cover` is the WP-blessed block for "image-with-text-overlay"
      hero/lookbook/banner surfaces. The block's `url` attribute is
      what gives it the actual cover painting; if you author it as
      `{"url":""}` (or omit `url` entirely) AND leave `dimRatio` at
      the default 0/low values, the block renders as a transparent
      box of `min-height` pixels with text positioned inside it.
      Visually that's a giant empty void above your headline -- the
      exact failure mode this check exists to catch (it shipped on
      Lysholm's front-page lookbook hero from 969b7f6 through 94dface,
      a ~720px transparent base-on-base box that nobody noticed because
      the text inside it WAS painted correctly and axe-core has no
      "huge empty space above headline" rule -- 0dfccab fixed the
      symptom by extracting the hero into
      `lysholm/patterns/hero-lookbook.php`; this gate prevents the
      same shape from re-appearing on a sixth theme).

      The failure mode is built into the workflow: static `.html`
      templates can't run PHP, so they can't inject
      `get_theme_file_uri( 'playground/images/foo.jpg' )` into a
      `wp:cover` `url` attribute. Authors who forget this end up
      leaving `"url":""` as a placeholder and shipping it. The fix
      is always the same -- extract the cover into a `.php` pattern
      where `get_theme_file_uri()` actually resolves, and reference
      it from the template via `<!-- wp:pattern {"slug":"…"} /-->`.
      `lysholm/patterns/hero-lookbook.php` is the worked example.

    What's allowed:
      * `wp:cover` with a non-empty `url` (image-backed cover -- the
        normal case).
      * `wp:cover` with `dimRatio >= 30` (a deliberately-painted color
        block masquerading as a cover -- used by selvedge's
        front-page.html for category cards). 30 is the WP editor's
        "noticeable tint" threshold; below that the overlay is mostly
        transparent and the block needs an image to show anything.
      * Cover markup inside `.php` patterns where the `url` value is
        a PHP expression (`<?php echo esc_url( … ); ?>`) -- the URL
        will be a real file path at render time.

    What's NOT allowed:
      * `wp:cover` with `url` empty/missing AND `dimRatio` < 30 in
        ANY file -- the block paints nothing.
    """
    r = Result("No empty `wp:cover` blocks (no transparent placeholder hero boxes)")

    cover_re = re.compile(r"<!--\s*wp:cover\s*(\{[^}]*\})\s*-->")
    skip_dirs = ("templates/", "parts/", "patterns/")

    files: list[Path] = []
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in skip_dirs):
            files.append(path)

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in cover_re.finditer(text):
            attrs_blob = m.group(1)
            url_match = re.search(r'"url"\s*:\s*"([^"]*)"', attrs_blob)
            url_value = url_match.group(1) if url_match else ""
            if "<?php" in url_value or "<?=" in url_value:
                continue
            if url_value.strip():
                continue
            dim_match = re.search(r'"dimRatio"\s*:\s*(\d+)', attrs_blob)
            dim_ratio = int(dim_match.group(1)) if dim_match else 0
            if dim_ratio >= 30:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            min_h_match = re.search(r"min-height:(\d+)px", text[m.start():m.start() + 800])
            min_h = (min_h_match.group(1) + "px") if min_h_match else "unknown-height"
            r.fail(
                f"{rel}:{lineno}: wp:cover with empty `url` and dimRatio={dim_ratio} "
                f"(< 30) renders as a transparent {min_h} void. "
                f"Either: (1) move the cover into a `.php` pattern where "
                f"`get_theme_file_uri('playground/images/<file>.jpg')` can "
                f"inject a real URL (see lysholm/patterns/hero-lookbook.php "
                f"for the worked example), (2) set `dimRatio>=30` with an "
                f"intentional `overlayColor` if you actually want a flat "
                f"color-block container, or (3) replace `wp:cover` with "
                f"`wp:group` + `backgroundColor` if you don't need the "
                f"image-overlay machinery."
            )

    if r.passed:
        r.details.append(f"{len(files)} pattern/template/part file(s) scanned; no empty wp:cover blocks")
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

    styles = data.get("styles", {}) or {}
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
                # Three accepted shapes, in order of recency:
                #   (a) the legacy short-hand reset, kept for back-compat with
                #       themes that haven't migrated to the per-theme
                #       `templates/page-my-account.html` pattern yet;
                #   (b) the body-prefixed, .entry-content-scoped grid that
                #       ships with the branded dashboard refactor (applies
                #       indiscriminately to .woocommerce children, including
                #       the logged-out login form which then breaks);
                #   (c) the same grid scoped via :has(>.woocommerce-MyAccount-
                #       navigation) so it ONLY fires on the logged-in dashboard
                #       (the logged-out login screen gets a separate 1fr 1fr
                #       grid scoped via :has(>.wo-account-intro) — see the
                #       my-account chunk in each theme's theme.json).
                ".woocommerce-account.woocommerce{display:grid;grid-template-columns:220px1fr",
                "body.woocommerce-account.entry-content>.woocommerce{display:grid",
                "body.woocommerce-account.entry-content>.woocommerce:has(>.woocommerce-MyAccount-navigation){display:grid",
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
                f'`styles.blocks["{target["inert_block"]}"].css`, but WP '
                f"wraps that field in `:root :where(...)` (specificity 0,0,1) "
                f"so it cannot beat WC's `(0,4,3)` plugin CSS. Move the WC "
                f"selectors to top-level `styles.css`."
            )
            continue

        # 2) Required selectors must appear (whitespace-insensitive) in the
        #    verbatim top-level styles.css.
        missing = [s for s in target["must_target"] if re.sub(r"\s+", "", s) not in top_css_norm]
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
        r"<!--\s*wp:group\s+(\{[^>]*?\})\s*-->",
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
            block = name[len("wp:") :]
            label = block
            if attrs_json:
                try:
                    attrs = json.loads(attrs_json)
                except json.JSONDecodeError:
                    attrs = {}
                if block == "pattern":
                    # Strip the theme-slug prefix from pattern slugs.
                    # Two themes that compose `<theme>/hero-split + grid
                    # + grid` are structurally identical even though
                    # `aero/hero-split` and `obel/hero-split` are
                    # technically different slugs. The prefix-stripped
                    # form is what matters for the "same shape, different
                    # paint" diversity test.
                    raw_slug = attrs.get("slug", "?")
                    bare = raw_slug.split("/", 1)[1] if "/" in raw_slug else raw_slug
                    label = f"pattern:{bare}"
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
            rel.startswith("templates/") or rel.startswith("parts/") or rel.startswith("patterns/")
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
        blocks = (data.get("styles") or {}).get("blocks") or {}
        if "woocommerce/product-details" in blocks:
            r.fail(
                'theme.json still has `styles.blocks["woocommerce/product-'
                'details"]`. The block is no longer rendered — delete the '
                "entry. Style `core/details` instead."
            )

    if r.passed and not r.skipped:
        r.details.append(
            "no WC tabs block in templates/parts/patterns and no stale theme.json styling"
        )
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
        renders_indicator = (
            re.search(r"<!--\s*wp:woocommerce/product-stock-indicator(?:\s|/|-->)", text)
            is not None
        )
        renders_form = (
            re.search(r"<!--\s*wp:woocommerce/add-to-cart-form(?:\s|/|-->)", text) is not None
        )
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
            f'`<p class="stock">` above the quantity input). The result is '
            f'"in stock" appearing twice on every PDP. Add a rule to '
            f"top-level `styles.css` matching one of "
            f"{selector_roots} (whitespace ignored) and "
            f"`display:none` so the form's stock paragraph is hidden. The "
            f"recommended selector list is: `form.cart .stock,"
            f".wp-block-add-to-cart-form .stock,"
            f".wc-block-add-to-cart-form__stock,"
            f".woocommerce-variation-availability {{ display: none; }}`. "
            f'Block-scoped `styles.blocks["woocommerce/add-to-cart-form"]'
            f".css` does NOT work — see check_wc_overrides_styled."
        )
        return r

    if "display:none" not in top_css_norm and "visibility:hidden" not in top_css_norm:
        r.fail(
            f"top-level `styles.css` matches `{matched_selector}` but never "
            f"declares `display:none` (or `visibility:hidden`). The form's "
            f'`<p class="stock">` is still visible — duplicating the '
            f"designed product-stock-indicator above."
        )
        return r

    if ".woocommerce-variation-availability" not in top_css_norm:
        r.fail(
            "stock paragraph is hidden, but `.woocommerce-variation-"
            "availability` isn't. On variable products WC renders a SECOND "
            'duplicate `<p class="stock">`-style line under the variation '
            "selector as the shopper picks attributes. Add "
            "`.woocommerce-variation-availability` to the same hide rule."
        )
        return r

    r.details.append(
        f"matched `{matched_selector}` + `display:none` + variation-"
        f"availability hide in top-level styles.css"
    )
    return r


def _srgb_lin(c: float) -> float:
    """sRGB component (0..1) -> linear-light component for WCAG luminance."""
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _wcag_luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance for a #RRGGBB hex string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return 0.2126 * _srgb_lin(r) + 0.7152 * _srgb_lin(g) + 0.0722 * _srgb_lin(b)


def _wcag_contrast(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x contrast ratio between two #RRGGBB hex strings (1..21)."""
    la, lb = _wcag_luminance(hex_a), _wcag_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def check_hover_state_legibility() -> Result:
    """Fail if any `:hover` / `:focus` / `:focus-visible` / `:active` rule
    in top-level `styles.css` produces text that's effectively invisible
    against the background it sits on.

    Why this exists:
      A theme can pass every other check and still ship a hover state
      that paints text in a color with ~1:1 contrast against the page.
      The classic case (caught in production review on chonk's cart
      page): `.button:hover { background: var(--accent); }` paints a
      yellow surface, but the button's default `color: var(--base)` is
      kept — so the button text becomes cream-on-yellow, contrast ~1.1:1,
      effectively invisible. Same shape: `.link:hover { color:
      var(--accent); }` on a theme whose accent is a saturated near-base
      hue (chonk's `#FFE600` sits 1.12:1 above the cream `--base`;
      lysholm's `#C9A97C` sits 2.04:1 above the cream `--base`).

      The bug is endemic to themes that copy WC override boilerplate
      across files without re-checking palette interactions: the same
      ruleset that's fine on a theme with a high-contrast accent silently
      fails on a theme whose accent collapses against the body bg. We
      need a check that runs *after* the palette and *after* the rules
      have been applied so it catches the palette/rule interaction.

    What this check enforces:
      For every rule in top-level `styles.css` whose selector contains
      `:hover`, `:focus`, `:focus-visible`, or `:active`:

      1. **Resolve effective text color.**
         - If the rule sets `color: var(--wp--preset--color--<X>)`, use
           palette[X].
         - Otherwise assume default `--contrast` (the inherited body
           text color in every theme in the monorepo).
      2. **Resolve effective background color.**
         - If the rule sets `background:` or `background-color:` to a
           palette token, use that.
         - If the rule sets a non-palette background (gradient, hex,
           transparent, none, etc.), skip the rule — we can't reason
           about contrast against an arbitrary value.
         - Otherwise assume default `--base` (the body background).
      3. **Compute WCAG contrast ratio** between the two resolved hex
         colors and require ≥ 3.0:1 (WCAG 2.x AA-Large bar — relaxed
         for state changes since they're typically transient and rarely
         long-form prose). Below 3.0 fails.

      Bullets 1+2 are deliberately conservative: an explicit text +
      explicit bg in the same rule are checked against each other; an
      explicit bg with no text declaration is checked against the
      assumed-default text color. The latter is exactly the
      `bg:accent` button-hover footgun.

    Tokens not present in the palette (e.g. typo, theme-specific custom
    name) are silently skipped so a typo doesn't masquerade as a
    contrast bug — `check_no_hex_in_theme_json` and theme.json schema
    validation catch those.
    """
    r = Result("Hover/focus states have legible text-vs-background contrast")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    palette_list = ((data.get("settings") or {}).get("color") or {}).get("palette") or []
    palette: dict[str, str] = {
        p["slug"]: p["color"]
        for p in palette_list
        if isinstance(p, dict)
        and isinstance(p.get("slug"), str)
        and isinstance(p.get("color"), str)
        and re.fullmatch(r"#[0-9A-Fa-f]{6}", p.get("color", ""))
    }
    if not palette or "base" not in palette or "contrast" not in palette:
        r.skip("palette is missing required `base` or `contrast` slug")
        return r

    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # Default text + bg if a rule doesn't set them and no resting state
    # is found. Every theme in the monorepo inherits
    # body { color: contrast; background: base; }.
    DEFAULT_TEXT = palette["contrast"]
    DEFAULT_BG = palette["base"]

    state_re = re.compile(r":(hover|focus|focus-visible|active)\b")
    color_re = re.compile(r"(?:^|[;{\s])color\s*:\s*var\(--wp--preset--color--([a-z0-9-]+)\)")
    bg_re = re.compile(r"\bbackground(?:-color)?\s*:\s*var\(--wp--preset--color--([a-z0-9-]+)\)")
    bg_unrecognised_re = re.compile(
        r"\bbackground(?:-color)?\s*:\s*(?!var\(--wp--preset--color--)([^;}]+)"
    )
    state_strip_re = re.compile(r":(?:hover|focus|focus-visible|active)\b")

    # Pre-build an index of every rule body by individual selector so we
    # can look up the resting-state declarations a `:hover` rule
    # inherits from. Necessary because a hover rule like
    # `.btn:hover { background: var(--accent); }` doesn't declare
    # `color:` -- but the resting `.btn { color: var(--base); }` does,
    # and that's the color that actually paints the hover text.
    rest_index: dict[str, list[str]] = {}
    for rest_match in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        sel_group, body_group = rest_match.group(1), rest_match.group(2)
        if state_re.search(sel_group):
            continue  # Only index resting-state rules.
        for raw_sel in sel_group.split(","):
            key = raw_sel.strip()
            if key:
                rest_index.setdefault(key, []).append(body_group)

    def _resting_color_token(hover_selectors: str) -> str | None:
        """For each comma-separated selector in the hover rule, strip the
        state pseudo-class and look up the resting rule(s). Return the
        first palette `color:` token declared on the resting state, or
        None if no resting rule sets one. We pick the first match in
        source order, which mirrors how a single rule's inherited text
        color gets resolved in practice (the most-specific resting rule
        for that exact selector is what wins for the hover state)."""
        for raw_sel in hover_selectors.split(","):
            resting_sel = state_strip_re.sub("", raw_sel).strip()
            if not resting_sel:
                continue
            for rest_body in rest_index.get(resting_sel, ()):
                m = color_re.search(rest_body)
                if m:
                    return m.group(1)
        return None

    failures: list[str] = []
    checked = 0

    for rule_match in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        sels, body = rule_match.group(1), rule_match.group(2)
        if not state_re.search(sels):
            continue

        # Resolve text color: hover's own declaration wins; otherwise
        # inherit from the resting state of the same selector; otherwise
        # fall back to the body default.
        color_match = color_re.search(body)
        if color_match:
            text_token = color_match.group(1)
            text_source = "hover"
        else:
            inherited = _resting_color_token(sels)
            if inherited is not None:
                text_token = inherited
                text_source = "inherited from resting state"
            else:
                text_token = None
                text_source = "body default"
        text_hex = palette.get(text_token) if text_token else DEFAULT_TEXT
        if text_token and text_hex is None:
            # Token not in palette (typo / custom name) — skip this rule.
            continue

        # Resolve background color.
        bg_match = bg_re.search(body)
        bg_token = bg_match.group(1) if bg_match else None
        bg_hex = palette.get(bg_token) if bg_token else None
        if bg_token and bg_hex is None:
            continue
        if bg_hex is None:
            # No palette bg in this rule. If the rule sets a non-palette
            # background (gradient, hex, transparent, etc.), we can't
            # reason about it — skip. Otherwise assume body default.
            unrec = bg_unrecognised_re.search(body)
            if unrec:
                continue
            bg_hex = DEFAULT_BG

        ratio = _wcag_contrast(text_hex, bg_hex)
        checked += 1
        if ratio < 3.0:
            # Pretty-print the offending selector list, capped to keep
            # the failure log scannable.
            sel_pretty = " ".join(sels.split())
            if len(sel_pretty) > 140:
                sel_pretty = sel_pretty[:137] + "..."
            color_desc = (
                f"`color: var(--{text_token})` ({text_hex}, {text_source})"
                if text_token
                else f"`color: var(--contrast)` ({text_hex}, body default)"
            )
            bg_desc = (
                f"`background: var(--{bg_token})` ({bg_hex})"
                if bg_token
                else f"inherited `background: var(--base)` ({bg_hex})"
            )
            failures.append(
                f"{sel_pretty}: {color_desc} vs {bg_desc} = "
                f"{ratio:.2f}:1, below the 3:1 floor. The hover state "
                f"renders the text effectively invisible against its "
                f"new background. Either flip `color:` to a palette "
                f"token that has ≥3:1 contrast with the new background "
                f"(usually `--contrast` for bright accents, `--base` "
                f"for dark backgrounds), or replace the bg-color shift "
                f"with a non-color hover signal (border, shadow, "
                f"underline-via-text-decoration-color)."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(f"{checked} hover/focus state rule(s) verified at ≥3:1 contrast")
    return r


def check_wc_card_surfaces_padded() -> Result:
    """Fail if any WC "panel/card" surface is given a `background:` in
    top-level `styles.css` without enough internal padding for the panel to
    breathe.

    Why this exists:
      The cart sidebar, checkout sidebar, mini-cart drawer, order-summary
      panel, etc. are *card surfaces* — opaque blocks that sit inside the
      page and hold dense compound content (subtotals, taxes, totals,
      coupon input, primary CTA, etc.). The moment we paint them with a
      non-transparent `background:` they READ as a panel and acquire the
      visual debt of a panel: shoppers expect generous internal padding,
      because the alternative — content butting up against the panel edge
      — looks like a half-finished plugin echo. The default WC theme.json
      block-scoped output ships these surfaces at `padding: lg` (≈24-40px
      depending on viewport), which is fine for type-only blocks but
      visibly cramped on a totals card with a price column on the right
      and a checkout button on the bottom. Reviewers reliably flag it as
      "feels like a default WooCommerce site".

      Worse, when these rules are written in `styles.blocks.*.css` they
      get wrapped in `:root :where(...)` (specificity 0,0,1) and lose the
      cascade fight with WC's own padding declarations. Once you've
      committed to overriding a card surface in top-level `styles.css`,
      the padding token MUST hold.

    What this check enforces:
      - For each KNOWN card surface (the WC selectors listed below),
        every top-level rule that sets a non-transparent `background:`
        must ALSO set padding (or padding-left + padding-right) using a
        spacing token of `xl` or larger.
      - Allowed tokens: `xl`, `2-xl`, `3-xl`, `4-xl`, `5-xl`. Anything
        smaller (`lg`, `md`, `sm`, `xs`, `2-xs`) fails — a panel painted
        with chrome below `xl` of internal padding is exactly the bug
        this check exists to prevent.
      - If a surface has padding split across multiple rules, ANY rule
        writing the bigger token is enough — we don't reject `padding:lg`
        if a sibling rule for the same selector sets `padding:xl` later.
        (This is permissive on purpose; the goal is "the panel breathes",
        not "the rule is written a specific way".)

      Surfaces that are styled but have no `background:` (transparent
      sections inside a parent panel) are skipped — they inherit the
      parent's padding context and don't need their own.

    See AGENTS.md "WooCommerce panel surfaces" rule.
    """
    r = Result("WC card surfaces have enough internal padding to breathe")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # WC selectors the theme paints as opaque card surfaces.
    # Add to this list as new surfaces get reskinned.
    CARD_SURFACES = [
        ".wc-block-cart__sidebar",
        ".wc-block-checkout__sidebar",
        ".wc-block-mini-cart__drawer .components-modal__content",
    ]

    # Spacing tokens that satisfy the "panel breathes" bar. Anything below
    # xl is intentionally rejected — see docstring.
    OK_TOKENS = ("xl", "2-xl", "3-xl", "4-xl", "5-xl")

    def _padding_token(decl_block: str) -> str | None:
        """Return the spacing slug used in `padding` / `padding-left` /
        `padding-right` declarations of a single CSS rule body, or None
        if no padding is set. Prefers `padding-left` over the shorthand
        because the shorthand can include 4 values."""
        # Try padding-left first (the side most visually responsible for
        # whether content reads as cramped against the panel edge).
        for prop in ("padding-left", "padding-inline", "padding"):
            for m in re.finditer(
                rf"\b{re.escape(prop)}\s*:\s*([^;}}]+)",
                decl_block,
            ):
                value = m.group(1)
                token_match = re.search(
                    r"var\(--wp--preset--spacing--([a-z0-9-]+)\)",
                    value,
                )
                if token_match:
                    return token_match.group(1)
        return None

    # Walk every rule of the form `<selectors> { <decls> }`. Group rules
    # by the card surface they target, accumulating which tokens we've
    # seen for that surface — a surface passes if ANY of its rules use a
    # qualifying token.
    seen_surfaces: dict[str, list[str]] = {}
    bg_surfaces: set[str] = set()
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        selectors_blob, body = m.group(1), m.group(2)
        # Strip CSS block comments from the selectors blob so a rule
        # whose head is glued to a sentinel comment (the way
        # `bin/append-wc-overrides.py` emits its chunks) still parses
        # cleanly — without this strip, the first selector in the
        # rule carries the leading `/* ... */` and never matches a
        # bare-string equality test.
        selectors_blob = re.sub(r"/\*.*?\*/", "", selectors_blob)
        # Multiple selectors per rule (`a, b, c { ... }`). For each card
        # surface, check if the rule's selector list mentions it as a
        # full selector (not a substring of a different selector — `+
        # \b` enforced by character-class lookbehind).
        sel_list = [s.strip() for s in selectors_blob.split(",")]
        for surface in CARD_SURFACES:
            for sel in sel_list:
                if (
                    sel == surface
                    or sel.startswith(surface + " ")
                    or sel.endswith(" " + surface)
                    or sel.startswith(surface + ":")
                    or sel.startswith(surface + ".")
                ):
                    if sel != surface:
                        # Only the *bare* selector (no descendant /
                        # state suffix) describes the panel itself; a
                        # descendant rule like `.wc-block-cart__sidebar
                        # .wp-block-heading` is internal type, not the
                        # panel.
                        continue
                    has_bg = (
                        re.search(
                            r"\bbackground(?:-color)?\s*:\s*(?!transparent\b|none\b|inherit\b|initial\b|unset\b)[^;}]+",
                            body,
                        )
                        is not None
                    )
                    if has_bg:
                        bg_surfaces.add(surface)
                    token = _padding_token(body)
                    if token:
                        seen_surfaces.setdefault(surface, []).append(token)

    # Only enforce the rule on surfaces that are actually painted as
    # opaque panels in this theme. Untouched surfaces are skipped —
    # the theme might not render the cart/checkout at all.
    if not bg_surfaces:
        r.skip("no WC card surfaces are painted with a background in this theme")
        return r

    failures: list[str] = []
    for surface in sorted(bg_surfaces):
        tokens = seen_surfaces.get(surface, [])
        if not tokens:
            failures.append(
                f"{surface}: top-level rule sets `background:` but no "
                f"`padding` (or `padding-left` / `padding-inline`) was "
                f"found on the bare selector. A painted panel without "
                f"explicit padding inherits zero from WC's reset and "
                f"reads as cramped. Add `padding: var(--wp--preset--"
                f"spacing--xl)` (or larger)."
            )
            continue
        if not any(t in OK_TOKENS for t in tokens):
            failures.append(
                f"{surface}: rule(s) set `background:` and `padding: "
                f"var(--wp--preset--spacing--{tokens[0]})`, but `"
                f"{tokens[0]}` is below the `xl` panel-breathing bar. "
                f"On a card surface holding totals + a primary CTA, "
                f"`lg` and below visibly cramps the content against "
                f"the panel edge. Bump to `xl` or larger."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(f"{len(bg_surfaces)} painted card surface(s) — all use ≥xl internal padding")
    return r


def check_wc_totals_blocks_padded() -> Result:
    """Fail if `wp-block-woocommerce-cart-totals-block` or
    `wp-block-woocommerce-checkout-totals-block` doesn't carry an
    `xl`-or-larger padding declaration in top-level `styles.css`.

    Why this is its own check (vs piggybacking on
    `check_wc_card_surfaces_padded`):

    `check_wc_card_surfaces_padded` is gated on the surface having a
    NON-TRANSPARENT `background:` painted on it — the assumption is "if
    you painted it as a panel, give it panel padding". That gate is
    correct for the SIDEBAR WRAPPER (`.wc-block-cart__sidebar` /
    `.wc-block-checkout__sidebar`) because that wrapper might be
    transparent on some themes (the base layer of the page bleeds
    through and there's no card to "breathe").

    The two TOTALS BLOCKS (`.wp-block-woocommerce-cart-totals-block`
    and `.wp-block-woocommerce-checkout-totals-block`) are different.
    In current WooCommerce blocks (9.x+) the totals block IS the
    visible "Order summary" card on every theme — it ALWAYS becomes
    the painted surface a shopper sees, because:

      * Phase C ships a `::before` "Order summary" pseudo-element
        directly on `.wp-block-woocommerce-cart-totals-block` /
        `.wp-block-woocommerce-checkout-totals-block`. That pseudo
        title sits at the top-left of whatever bounds those selectors
        own; if they have no padding, the title sits flush at the
        edge.
      * The WC block markup renders the totals block at width:100%
        inside the sidebar wrapper. If the sidebar wrapper is
        unpainted (or painted the same color as the page background,
        like Selvedge's dark base where `--surface` ≈ page bg), the
        totals block IS the visible card, and the only thing inset
        from its perimeter is whatever padding the totals block
        itself declares.

    So even if the SIDEBAR WRAPPER passes
    `check_wc_card_surfaces_padded`, the inner totals block can still
    render edge-to-edge content (the bug we're preventing). This check
    closes that gap by enforcing padding on the totals blocks
    UNCONDITIONALLY — no background prerequisite, because in modern
    WC the totals block is always the visible card surface on at
    least some themes.

    What this check enforces:

      * For each of the two totals selectors above, at least one
        top-level `styles.css` rule whose selector list mentions the
        bare selector must declare `padding`, `padding-left`, or
        `padding-inline` using a spacing token of `xl` or larger
        (`xl`, `2-xl`, `3-xl`, `4-xl`, `5-xl`).
      * If multiple rules apply, the bigger token wins (matches the
        permissive semantics in `check_wc_card_surfaces_padded`).

    Enforced at write time by:
      `bin/append-wc-overrides.py` Phase H
      (`wc-tells-phase-h-totals-padding`), which emits the baseline
      `padding: xl` on these selectors into every theme's
      `styles.css`.

    See AGENTS.md "WooCommerce panel surfaces" rule for the broader
    context.
    """
    r = Result("WC totals blocks (cart + checkout) have ≥xl internal padding")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # The two selectors that ALWAYS render as the visible "Order
    # summary" card in current WC. Add to this list as new always-
    # painted totals containers ship in WC.
    TOTALS_SELECTORS = (
        ".wp-block-woocommerce-cart-totals-block",
        ".wp-block-woocommerce-checkout-totals-block",
    )
    OK_TOKENS = ("xl", "2-xl", "3-xl", "4-xl", "5-xl")

    def _padding_tokens(decl_block: str) -> list[str]:
        """Collect every spacing slug used in any `padding`-family
        declaration of a single rule body. Returns [] if nothing
        token-shaped is found."""
        tokens: list[str] = []
        for prop in ("padding-left", "padding-inline", "padding"):
            for m in re.finditer(
                rf"\b{re.escape(prop)}\s*:\s*([^;}}]+)",
                decl_block,
            ):
                value = m.group(1)
                tokens.extend(
                    re.findall(
                        r"var\(--wp--preset--spacing--([a-z0-9-]+)\)",
                        value,
                    )
                )
        return tokens

    # selector -> list of every padding token we saw on the bare
    # selector across every rule in top-level styles.css.
    seen: dict[str, list[str]] = {sel: [] for sel in TOTALS_SELECTORS}

    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        selectors_blob, body = m.group(1), m.group(2)
        # Strip CSS block comments from the selectors blob so a
        # rule that's prefixed with sentinel markers (the way
        # `bin/append-wc-overrides.py` emits its chunks) still
        # parses cleanly. Without this strip the FIRST selector
        # in the rule has the sentinel comment glued to its head
        # and `sel == surface` never matches.
        selectors_blob = re.sub(r"/\*.*?\*/", "", selectors_blob)
        sel_list = [s.strip() for s in selectors_blob.split(",")]
        for surface in TOTALS_SELECTORS:
            for sel in sel_list:
                # Only the BARE selector (or a selector list that
                # contains the bare selector as one of its entries)
                # describes the panel itself; descendant rules like
                # `.wp-block-woocommerce-cart-totals-block .heading`
                # are inner type, not the panel.
                if sel == surface:
                    seen[surface].extend(_padding_tokens(body))

    failures: list[str] = []
    for surface in TOTALS_SELECTORS:
        tokens = seen[surface]
        if not tokens:
            failures.append(
                f"{surface}: no `padding` (or `padding-left` / "
                f"`padding-inline`) declaration found on the bare "
                f"selector in top-level `styles.css`. This block is "
                f"the visible 'Order summary' card on current WC; "
                f"without explicit padding its content sits flush at "
                f"the panel edge. Re-run `bin/append-wc-overrides.py` "
                f"to (re-)emit Phase H, or add `padding: var(--wp--"
                f"preset--spacing--xl)` (or larger) to a top-level "
                f"rule whose selector list contains exactly `{surface}`."
            )
            continue
        if not any(t in OK_TOKENS for t in tokens):
            biggest = tokens[0]
            failures.append(
                f"{surface}: padding token `{biggest}` is below the "
                f"`xl` panel-breathing bar. The totals card is dense "
                f"(subtotal + tax + total + coupon row + primary "
                f"CTA); `lg` and below visibly cramps the stack "
                f"against the panel edge. Bump to `xl` or larger."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(
        f"{len(TOTALS_SELECTORS)} totals block(s) — all carry ≥xl internal padding (Phase H)"
    )
    return r


def check_wc_notices_styled() -> Result:
    """Fail if the Phase L `wc-tells-phase-l-notices` sentinel block is
    missing from a theme's `theme.json` root `styles.css`, or if the
    block is present but doesn't carry the canonical surface-restyling
    rules.

    Why this exists:
      WooCommerce paints notices in five different markup shapes
      (modern Blocks notice banner, per-field validation error,
      snackbar, store-notices wrapper, and the classic
      `.woocommerce-message`/`-error`/`-info` triad). Out of the box
      every one of them paints with WC's hardcoded plugin voice
      (white pill background, stock SVG icon, sans-serif at a fixed
      size, no theme tokens) — exactly the "this is a free
      WooCommerce site" failure mode this monorepo exists to prevent.
      The fix lives in `bin/append-wc-overrides.py` Phase L, which
      ships token-driven chrome that uses each theme's existing
      `info` / `success` / `warning` / `error` palette tokens for the
      variant signal so the same chunk paints per-theme without any
      raw hex.

      A regression on this surface is invisible during normal demo
      browsing (notices only appear when the shopper triggers
      something — failed login, invalid coupon, sold-out variation,
      etc.), so the static gate has to enforce the chunk's presence
      directly. Without this check, someone hand-stripping the
      Phase L chunk to re-author it inline (and forgetting to commit
      the replacement) ships a theme whose notice surfaces silently
      revert to WC's plugin defaults, and the regression only shows
      up the next time a shopper triggers a notice in the live demo.

    What this check enforces:
      - The Phase L sentinel pair (`/* wc-tells-phase-l-notices */`
        … `/* /wc-tells-phase-l-notices */`) is present in
        `theme.json` root `styles.css`.
      - Inside the sentinel block, the canonical surface restyles
        are present:
          * the modern banner selector
            `.wc-block-components-notice-banner`,
          * the four variant signals (`.is-info`, `.is-success`,
            `.is-warning`, `.is-error`),
          * the per-field validation error
            (`.wc-block-components-validation-error`),
          * the snackbar list
            (`.wc-block-components-notices__snackbar` OR
            `.wc-block-components-notice-snackbar-list`),
          * the legacy classic triad
            (`.woocommerce-message`, `.woocommerce-error`,
            `.woocommerce-info`).

    Enforced at write time by:
      `bin/append-wc-overrides.py` Phase L (`wc-tells-phase-l-notices`).
      Re-run the script after any styles.css drift to regenerate
      the chunk.
    """
    r = Result("WC notice surfaces are restyled (banner + validation + snackbar)")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    open_marker = "/* wc-tells-phase-l-notices */"
    close_marker = "/* /wc-tells-phase-l-notices */"
    open_idx = top_css.find(open_marker)
    close_idx = top_css.find(close_marker)
    if open_idx < 0 or close_idx < 0 or close_idx <= open_idx:
        r.fail(
            "Phase L sentinel block (wc-tells-phase-l-notices) is "
            "missing from `theme.json` root `styles.css`. The chunk "
            "ships token-driven restyles for every WC notice surface "
            "(modern banner, per-field validation error, snackbar, "
            "store-notices wrapper, classic message/error/info). "
            "Without it, every notice paints with WC's hardcoded "
            "plugin voice. Re-run `python3 bin/append-wc-overrides.py` "
            "to (re-)emit Phase L."
        )
        return r

    chunk = top_css[open_idx:close_idx]
    chunk_norm = re.sub(r"\s+", "", chunk)

    required = (
        ("modern banner", ".wc-block-components-notice-banner"),
        ("info variant", ".wc-block-components-notice-banner.is-info"),
        ("success variant", ".wc-block-components-notice-banner.is-success"),
        ("warning variant", ".wc-block-components-notice-banner.is-warning"),
        ("error variant", ".wc-block-components-notice-banner.is-error"),
        ("validation error", ".wc-block-components-validation-error"),
        ("legacy message", ".woocommerce-message"),
        ("legacy error", ".woocommerce-error"),
        ("legacy info", ".woocommerce-info"),
    )
    missing: list[str] = []
    for label, selector in required:
        if re.sub(r"\s+", "", selector) not in chunk_norm:
            missing.append(f"{label} (`{selector}`)")

    snackbar_selectors = (
        ".wc-block-components-notices__snackbar",
        ".wc-block-components-notice-snackbar-list",
    )
    if not any(re.sub(r"\s+", "", s) in chunk_norm for s in snackbar_selectors):
        missing.append(
            "snackbar (one of `.wc-block-components-notices__snackbar` "
            "or `.wc-block-components-notice-snackbar-list`)"
        )

    if missing:
        r.fail(
            "Phase L sentinel block exists but is missing canonical "
            "notice surface restyles for: " + ", ".join(missing) + ". "
            "Re-run `python3 bin/append-wc-overrides.py` to regenerate "
            "the chunk."
        )
        return r

    r.details.append(f"Phase L block present + {len(required)} surface restyles + snackbar covered")
    return r


def check_navigation_overlay_opaque() -> Result:
    """Fail if any `core/navigation` block in `parts/` (or `templates/`)
    opens a mobile overlay menu without explicit `overlayBackgroundColor`
    and `overlayTextColor` attributes pointing at palette tokens.

    Why this exists:
      WordPress core's mobile navigation overlay (the modal that opens
      when the hamburger is tapped) ships with `background-color: inherit`
      as the default paint. When the surrounding header is also a
      transparent or `inherit`-colored container, the modal renders
      transparent — the underlying page (heading, hero image, etc.)
      bleeds straight through behind the menu items, leaving the user
      staring at a stack of unreadable links floating over a `Lookbook`
      hero. The fix is to set `overlayBackgroundColor` (and a paired
      `overlayTextColor`) directly on the `core/navigation` block so the
      block emits its own `--navigation-overlay-background-color` /
      `--navigation-overlay-text-color` custom properties at the right
      specificity. WP core then paints the modal opaquely on every
      breakpoint with no theme.json shim required.

      A regression on this surface is invisible during normal desktop
      browsing (the modal only opens on mobile / when `overlayMenu`
      kicks in), so the static gate has to enforce the attributes
      directly. Without this check, anyone hand-editing `parts/header.html`
      (or copy-pasting a nav block from another part) ships a header
      whose mobile menu silently reverts to the bleed-through default,
      and the regression only shows up the next time someone opens the
      site on a phone.

    What this check enforces:
      For every `core/navigation` block found in `parts/*.html` and
      `templates/*.html` whose `overlayMenu` attribute is set to anything
      other than `"never"` (i.e. `"mobile"` or `"always"` — the two
      values WP supports that actually open the modal):
        - `overlayBackgroundColor` MUST be present and resolve to a
          palette slug declared in `settings.color.palette`.
        - `overlayTextColor` MUST be present and resolve to a palette slug
          declared in `settings.color.palette`.

      Custom hex colors via `style.color.background` / `style.color.text`
      are intentionally rejected — palette tokens keep the overlay
      brand-coherent across light/dark mode and palette swaps. If a theme
      genuinely needs a one-off color, add it to the palette first.
    """
    r = Result("Navigation overlay menus paint with palette tokens")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    palette = ((data.get("settings") or {}).get("color") or {}).get("palette") or []
    palette_slugs = {p.get("slug") for p in palette if isinstance(p, dict)}

    candidates: list[Path] = []
    for sub in ("parts", "templates"):
        d = ROOT / sub
        if d.is_dir():
            candidates.extend(sorted(d.glob("*.html")))

    if not candidates:
        r.skip("no parts/ or templates/ to scan")
        return r

    nav_open_re = re.compile(r"<!--\s*wp:navigation\s+(\{.*?\})\s*(/?)-->", re.DOTALL)
    failures: list[str] = []
    nav_blocks_seen = 0

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in nav_open_re.finditer(text):
            attrs_raw = match.group(1)
            try:
                attrs = json.loads(attrs_raw)
            except json.JSONDecodeError:
                failures.append(
                    f"{path.relative_to(ROOT)}: `core/navigation` block has "
                    f"un-parseable JSON attrs near offset {match.start()}."
                )
                continue
            nav_blocks_seen += 1
            overlay_mode = attrs.get("overlayMenu", "mobile")
            if overlay_mode == "never":
                continue
            rel = path.relative_to(ROOT)
            bg = attrs.get("overlayBackgroundColor")
            fg = attrs.get("overlayTextColor")
            if not bg:
                failures.append(
                    f'{rel}: `core/navigation` (overlayMenu="{overlay_mode}") '
                    f"is missing `overlayBackgroundColor`. Without it WP core "
                    f"paints the mobile modal `background-color: inherit`, so "
                    f"the page bleeds through behind the menu items. Set it to "
                    f'a palette slug, e.g. `"overlayBackgroundColor":"base"`.'
                )
            elif bg not in palette_slugs:
                failures.append(
                    f"{rel}: `core/navigation` `overlayBackgroundColor` "
                    f"=`{bg}` is not a slug in `settings.color.palette`. "
                    f"Use a palette token so the overlay survives palette "
                    f"swaps and dark mode."
                )
            if not fg:
                failures.append(
                    f'{rel}: `core/navigation` (overlayMenu="{overlay_mode}") '
                    f"is missing `overlayTextColor`. Pair it with "
                    f"`overlayBackgroundColor` so the menu text reads against "
                    f'the modal paint, e.g. `"overlayTextColor":"contrast"`.'
                )
            elif fg not in palette_slugs:
                failures.append(
                    f"{rel}: `core/navigation` `overlayTextColor`=`{fg}` "
                    f"is not a slug in `settings.color.palette`. Use a "
                    f"palette token so the menu text inherits the theme's "
                    f"voice."
                )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if nav_blocks_seen == 0:
        r.skip("no core/navigation blocks found")
        return r

    r.details.append(
        f"{nav_blocks_seen} `core/navigation` block(s) carry palette-token overlay paint"
    )
    return r


def check_outline_button_paired_with_primary() -> Result:
    """Fail if `theme.json` defines an `is-style-outline` variation for
    `core/button` that isn't visually paired with the primary button —
    i.e. its border-radius doesn't match the primary, or its border-width
    is hairline-thin (≤1px) while the primary carries visible heft.

    Why this exists:
      Primary and outline buttons almost always render side-by-side
      ("Shop the bench" + "Read the journal", "Add to cart" + "Continue
      shopping", etc.). For the pair to read as ONE coordinated CTA,
      they need to share the same shape grammar — same corner radius,
      comparable border weight, the same approximate footprint. WP
      core's stock `is-style-outline` ships with a 1px hairline border
      and inherits whatever radius the variation declares, but that
      radius is independent of `styles.elements.button.border.radius`.
      The two can drift apart silently:

        * a designer rounds the primary to a pill but leaves the outline
          square (or vice-versa), and suddenly the pair looks like two
          different design systems mashed together;
        * the outline ships at `border-width: 1px` next to a primary
          that sits at `var(--border--width--thick)` (2-3px), and the
          outline reads as a faint suggestion rather than a real CTA.

      Both failure modes are baked into WP's stock outline style. The
      fix is to declare an outline variation in
      `styles.blocks.core/button.variations.outline` whose `border.radius`
      matches the primary's `styles.elements.button.border.radius` and
      whose `border.width` is ≥ 2px (or a `--border--width--thick`-style
      token that resolves to ≥ 2px).

    What this check enforces:
      For every theme that declares
      `styles.blocks.core/button.variations.outline.border`:
        - `outline.border.radius` MUST equal
          `styles.elements.button.border.radius` when both are set.
          (If primary has no `border.radius` set, the outline's radius
          is unconstrained — WP defaults to the same UA value for both.)
        - `outline.border.width` MUST NOT be a literal `1px` / `0` /
          `none`. The check passes any token reference
          (`var(--wp--custom--border--width--*)`) under the assumption
          that the token itself is ≥ 2px (the
          `check_distinctive_chrome` companion already verifies token
          values across themes); literal `2px`/`3px`/`4px` etc. are
          also accepted.
        - `outline.border.style` MUST be present and not `none`.
        - `outline.color.background` MUST be `transparent` (or absent —
          WP defaults to transparent for outline) so the variation
          actually reads as outlined; if it's a solid color, the
          author probably meant to add a third button variation, not
          an "outline".

      Themes with no `outline` variation declared are skipped (the
      check has nothing to enforce — no outline means no mispairing).
    """
    r = Result("Outline button variation is visually paired with primary")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    styles = data.get("styles") or {}
    btn_elem = (styles.get("elements") or {}).get("button") or {}
    primary_border = (btn_elem.get("border") or {}) if isinstance(btn_elem, dict) else {}
    primary_radius = primary_border.get("radius")

    blocks_btn = (styles.get("blocks") or {}).get("core/button") or {}
    outline = (blocks_btn.get("variations") or {}).get("outline") or {}
    if not outline:
        r.skip("no outline variation declared on core/button")
        return r

    out_border = outline.get("border") or {}
    out_color = outline.get("color") or {}

    failures: list[str] = []

    out_radius = out_border.get("radius")
    if primary_radius is not None and out_radius != primary_radius:
        failures.append(
            f"`styles.blocks.core/button.variations.outline.border.radius`="
            f"`{out_radius}` does not match the primary "
            f"`styles.elements.button.border.radius`=`{primary_radius}`. "
            f"A primary + outline pair that disagrees on corner shape "
            f"reads as two different design systems mashed together. "
            f"Set both to the same value (or remove the outline radius "
            f"to inherit the primary's)."
        )

    out_width = out_border.get("width")
    if out_width is None:
        failures.append(
            "`styles.blocks.core/button.variations.outline.border.width` "
            "is not set. Outline buttons need an explicit border-width — "
            "WP's UA default of 0 is invisible. Set it to "
            "`var(--wp--custom--border--width--thick)` (or any value ≥2px)."
        )
    else:
        # Reject anything that resolves to a hairline / nothing.
        # Accept token references (assumed ≥2px; verified by token check).
        thin = {"0", "0px", "none", "1px", ".5px", "0.5px"}
        if isinstance(out_width, str):
            ws = out_width.strip().lower()
            if ws in thin:
                failures.append(
                    f"`styles.blocks.core/button.variations.outline.border.width`="
                    f"`{out_width}` is too thin to balance a primary CTA. "
                    f"A 1px outline next to a chunky filled primary reads "
                    f"as a faint suggestion rather than a real button. "
                    f"Use `var(--wp--custom--border--width--thick)` (or "
                    f"any literal ≥2px)."
                )

    out_style = out_border.get("style")
    if out_style in (None, "none"):
        failures.append(
            f"`styles.blocks.core/button.variations.outline.border.style`="
            f"`{out_style}` — an outline variation needs a visible "
            f"border-style (typically `solid`)."
        )

    out_bg = out_color.get("background")
    if out_bg not in (None, "transparent"):
        failures.append(
            f"`styles.blocks.core/button.variations.outline.color.background`="
            f"`{out_bg}` — an `is-style-outline` variation should paint "
            f"`transparent` so the border carries the chrome. If you want "
            f"a third filled-but-different variation, register it under a "
            f"different name (e.g. `secondary`) so its intent is explicit."
        )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(
        f"outline variation paired with primary (radius=`{out_radius}`, width=`{out_width}`)"
    )
    return r


def check_wc_card_padding_not_zeroed() -> Result:
    """Fail if any rule in top-level `styles.css` zeros horizontal
    padding on a painted WC card surface.

    Why this is its own check (vs trusting
    `check_wc_card_surfaces_padded` and `check_wc_totals_blocks_padded`
    to enforce the floor):

    Those two checks verify that *some* rule declares an `xl`-or-bigger
    padding on the bare selector. They do NOT verify that no
    higher-specificity rule elsewhere in the same `styles.css` quietly
    UNDECLARES that padding — which is exactly the regression that
    shipped in Q2 when `wc-tells-grid-cell-fill` zeroed
    `padding-left` and `padding-right` on
    `.wc-block-components-sidebar-layout.wc-block-cart > .wc-block-
    components-sidebar` (specificity `(0,3,0)`). The DOM that matched
    that selector is the SAME element that carries
    `.wc-block-cart__sidebar` AND
    `.wp-block-woocommerce-cart-totals-block`, so the painted-card
    rules at specificity `(0,1,0)` lost the cascade and the "Order
    summary" stack rendered flush at the panel's left edge across
    every theme. The bug was visually invisible to the existing
    "panel has padding declared" checks because the bare-selector
    rule still declared `padding: xl` — it just got overruled.

    What this check enforces:

      * For each rule in top-level `styles.css`, parse the selector
        list and the declaration block.
      * If any selector in the list contains one of the painted card
        surface class names listed in `_CARD_SURFACE_CLASSES` below,
        AND the rule body declares any of `padding`, `padding-left`,
        `padding-right`, `padding-inline`, `padding-inline-start`,
        `padding-inline-end` with a literal `0` value (with or
        without a unit suffix), the check fails with a pointer to
        the offending selector and declaration.
      * Whitelist: the bare card-surface selectors themselves
        (e.g. `.wc-block-cart__sidebar`) are allowed to set
        `padding: 0` on RESET-style chunks if a sibling rule re-paints
        the padding back. We don't bother detecting that: in practice,
        no current chunk needs to zero padding on a painted card, so
        any match is the regression we're guarding against.

    Companion to:
      * `check_wc_card_surfaces_padded` — verifies the floor.
      * `check_wc_totals_blocks_padded` — verifies the totals card
        floor specifically.
      * `bin/append-wc-overrides.py::CSS_GRID_FIX` block comment —
        the load-bearing reminder that explains WHY GRID_FIX no
        longer zeros padding (and what to do if WC's percentage
        paddings ever leak back).
    """
    r = Result("WC painted card surfaces don't get horizontal padding zeroed")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # The painted card surfaces. A rule that matches ANY of these
    # classes (anywhere in any of its selectors) and zeros horizontal
    # padding will UNDO the panel's breathing room because the DOM
    # node carrying these classes is the visible card a shopper sees.
    _CARD_SURFACE_CLASSES = (
        "wc-block-cart__sidebar",
        "wc-block-checkout__sidebar",
        "wp-block-woocommerce-cart-totals-block",
        "wp-block-woocommerce-checkout-totals-block",
        # `.wc-block-components-sidebar` shares its DOM node with
        # `.wc-block-cart__sidebar` and `.wc-block-checkout__sidebar`
        # (verified in WC blocks 9.x markup), so a rule targeting
        # the components-sidebar class on a cart/checkout host is
        # ALSO painting the card. This catches the original
        # GRID_FIX regression directly.
        "wc-block-components-sidebar",
    )

    # CSS values that count as "zeroing horizontal padding": bare 0,
    # 0px, 0rem, 0em, 0%, 0vh, 0vw, etc. We deliberately do NOT match
    # `padding: 0 var(--xl)` or `padding: 0 1rem` because those leave
    # horizontal padding intact — only the vertical is zeroed and the
    # card still breathes left-to-right. The regex is anchored on a
    # word boundary so we don't false-positive on `0.5rem`.
    _ZERO_VALUE_RE = re.compile(r"^\s*0(?:px|rem|em|%|vh|vw|vmin|vmax)?\s*$")

    # The padding properties that, if set to 0, would strip the
    # horizontal breathing room. `padding-top` / `padding-bottom` are
    # intentionally NOT in this list — vertical zero is fine, the
    # check is about left/right inset only.
    _HORIZONTAL_PADDING_PROPS = (
        "padding-left",
        "padding-right",
        "padding-inline",
        "padding-inline-start",
        "padding-inline-end",
    )

    failures: list[str] = []

    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        selectors_blob, body = m.group(1), m.group(2)
        # Strip CSS block comments so sentinel-prefixed rules parse
        # cleanly (mirrors the strip in
        # `check_wc_totals_blocks_padded`).
        selectors_blob = re.sub(r"/\*.*?\*/", "", selectors_blob)
        selectors_blob = selectors_blob.strip()
        if not selectors_blob:
            continue
        sel_list = [s.strip() for s in selectors_blob.split(",")]
        # Find every selector that targets a painted card surface.
        offending_selectors = [
            s for s in sel_list if any(f".{cls}" in s for cls in _CARD_SURFACE_CLASSES)
        ]
        if not offending_selectors:
            continue
        # Walk the declaration block looking for any
        # `padding-{left,right,inline,inline-start,inline-end}: 0`
        # OR a shorthand `padding: 0` (the latter zeros all four
        # sides, including horizontal).
        for prop in _HORIZONTAL_PADDING_PROPS:
            for d in re.finditer(
                rf"\b{re.escape(prop)}\s*:\s*([^;}}]+)",
                body,
            ):
                value = d.group(1).strip()
                # Only flag rules that set the property to a literal
                # zero. `var(--xl)`, `revert`, `unset`, etc. are all
                # fine — they restore breathing room.
                if _ZERO_VALUE_RE.match(value):
                    failures.append(
                        f"{', '.join(offending_selectors)} "
                        f"sets `{prop}: {value}` — this strips "
                        f"horizontal padding from a painted card "
                        f"surface and undoes Phase G/H/cart-fix's "
                        f"breathing room. See "
                        f"`bin/append-wc-overrides.py::CSS_GRID_FIX` "
                        f"comment for the regression history."
                    )
        # Shorthand `padding: 0` is the other way to zero horizontal
        # padding. We allow `padding: 0 <something-non-zero>` (vertical
        # zero, horizontal painted) and `padding: 0 ... ...` only when
        # the second value is non-zero.
        for d in re.finditer(r"\bpadding\s*:\s*([^;}]+)", body):
            value = d.group(1).strip()
            parts = value.split()
            if not parts:
                continue
            # If the shorthand is JUST `0` (one value), all four sides
            # are zero — horizontal included.
            if len(parts) == 1 and _ZERO_VALUE_RE.match(parts[0]):
                failures.append(
                    f"{', '.join(offending_selectors)} sets "
                    f"`padding: {value}` — single-value `0` zeros "
                    f"all four sides, including horizontal, and "
                    f"strips the painted card's breathing room."
                )
                continue
            # If the shorthand is `0 0 ... ...` (two or four values
            # where the SECOND value is zero), horizontal is zero.
            if len(parts) >= 2 and _ZERO_VALUE_RE.match(parts[1]):
                failures.append(
                    f"{', '.join(offending_selectors)} sets "
                    f"`padding: {value}` — the horizontal slot "
                    f"is `0`, which strips the painted card's "
                    f"breathing room."
                )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(
        f"{len(_CARD_SURFACE_CLASSES)} card-surface class(es) — no "
        f"rule zeros horizontal padding on a painted card"
    )
    return r


# Selectors that paint user-visible "chrome" — the parts of the storefront
# where a shopper sees this theme's voice and not the next theme's. Each
# entry is matched VERBATIM against rule selectors in top-level `styles.css`
# (whitespace normalised, but selector lists must match in order).
#
# Rule: nothing in this list is allowed to ship a byte-identical CSS body in
# two or more themes UNLESS each of those themes also provides a per-theme
# `body.theme-<slug> <selector>` override that visually overpowers the base.
# A "standard" treatment shared across themes is exactly the "feels like a
# default WooCommerce site" bug we keep flagging on demos.
#
# Add a selector here whenever a new premium-chrome surface ships (cart
# sidebar, primary CTA chrome, sale badge, hero, trust strip, footer mark,
# …). Structural / utility / accessibility rules are deliberately NOT in
# this list — a `min-width:0` overflow fix or a screen-reader visually-
# hidden rule SHOULD be byte-identical across themes; that's not chrome,
# that's plumbing.
DISTINCT_CHROME_SELECTORS: list[str] = [
    ".wc-block-cart__sidebar",
    ".wc-block-checkout__sidebar",
    ".wo-payment-icons__icon",
]

# All four shipped themes. Used by cross-theme checks (the ones that have
# to load every sibling's CSS, not just the current ROOT).
_KNOWN_THEME_SLUGS = ("chonk", "obel", "selvedge", "lysholm", "aero")


def _normspace(s: str) -> str:
    """Collapse all whitespace runs in a CSS fragment so two rules can be
    compared byte-for-byte without being defeated by minifier whitespace."""
    return re.sub(r"\s+", "", s)


def _strip_css_comments(css: str) -> str:
    """Remove every `/* ... */` block from a CSS string. The phase-N
    sentinels appended by `bin/append-wc-overrides.py` live as comments
    immediately before each rule, so without stripping them the regex
    below ends up capturing `<comment> <selector> {...}` as one selector
    blob — and `selector.startswith("body.theme-…")` then never matches."""
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.DOTALL)


def _find_base_rule_body(css: str, target_selector: str) -> str | None:
    """Return the normalised body of the FIRST top-level rule whose selector
    list (whitespace-normalised) exactly equals `target_selector`. We compare
    the whole selector list — comma-separated bundles like `a,b,c` must
    match in their entirety, because changing the bundle is itself a
    legitimate way to make a theme's chrome distinctive.

    Returns None if no matching rule exists. Skips selectors that begin
    with `body.theme-` because those are per-theme overrides, not the base.
    """
    target_norm = _normspace(target_selector)
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", _strip_css_comments(css)):
        sel_blob, body = m.group(1), m.group(2)
        sel_norm = _normspace(sel_blob)
        if sel_norm.startswith("body.theme-"):
            continue
        if sel_norm == target_norm:
            return _normspace(body)
    return None


def _has_per_theme_override(css: str, theme_slug: str, target_selector: str) -> bool:
    """Return True iff `css` contains at least one rule whose selector list
    starts with `body.theme-<slug>` and whose remainder mentions any of the
    comma-separated parts of `target_selector` as the trailing component.

    Phase E/F overrides live in the same blob as the base rules (the
    bin/append-wc-overrides.py CSS chunk is appended verbatim to every
    theme's styles.css), so the override for chonk is present in *every*
    theme's CSS — the body class is what gates which one fires at runtime.
    Checking presence in any theme's CSS is therefore equivalent to
    checking that the override exists at all.
    """
    target_parts = [_normspace(p) for p in target_selector.split(",")]
    prefix = f"body.theme-{theme_slug}"
    for m in re.finditer(r"([^{}]+)\{[^}]*\}", _strip_css_comments(css)):
        sel_blob = m.group(1)
        for raw_sel in sel_blob.split(","):
            sel_norm = _normspace(raw_sel)
            if not sel_norm.startswith(prefix):
                continue
            rest = sel_norm[len(prefix) :]
            if not rest.startswith("."):
                # Prefix must be followed by a descendant combinator
                # (which gets normalised away); a bare `body.theme-X` rule
                # wouldn't be a per-selector override.
                continue
            for part in target_parts:
                if rest.endswith(part):
                    return True
    return False


def check_distinctive_chrome() -> Result:
    """Fail if any "premium chrome" selector (see DISTINCT_CHROME_SELECTORS)
    ships a byte-identical CSS body in two or more themes WITHOUT a
    per-theme `body.theme-<slug> <selector>` override that lets each theme
    in the cluster express its own voice.

    Why this exists
    ---------------
    The fastest way to make a WooCommerce demo read as "off-the-shelf" is
    to paint the visible chrome the same way in every theme variant. The
    cart sidebar, the checkout sidebar, the trust-strip pills, the primary
    CTA — these are exactly the surfaces a shopper looks at to answer
    "does this brand have its own taste?" If chonk and obel render the
    payment-icon row with byte-identical white pills, both themes lose
    the answer.

    The rule isn't "no shared CSS rules anywhere" — utility and structural
    plumbing (overflow fixes, screen-reader helpers, layout grids) MUST
    be byte-identical or the themes drift inconsistently. The rule is
    scoped to the curated DISTINCT_CHROME_SELECTORS list, which lives at
    the top of this file and is meant to grow as new chrome surfaces
    ship.

    What "distinctive" means here
    -----------------------------
    A theme can earn a unique treatment two ways:
      1. Its base rule body for the selector differs from the other
         themes' base rule bodies. (Chonk just authors a different rule
         in `styles.blocks` or `styles.css`.)
      2. The base rule body is shared across themes, but EACH theme in
         the shared cluster also provides a `body.theme-<slug>
         <selector>` override (in `bin/append-wc-overrides.py` Phase E
         or Phase F) that visibly differentiates it.

    Either path satisfies the rule.

    What this check enforces
    ------------------------
    For every selector S in DISTINCT_CHROME_SELECTORS:
      - Load every shipped theme's top-level styles.css (cross-theme).
      - Group themes by the byte-identical base rule body for S.
      - For each cluster of 2+ themes with the same body, fail any
        theme in the cluster that does NOT also ship a per-theme
        override for S.
    """
    r = Result("Visible chrome rules are theme-distinct (no shared 'standard' look)")

    theme_css: dict[str, str] = {}
    for slug in _KNOWN_THEME_SLUGS:
        path = MONOREPO_ROOT / slug / "theme.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        css = (data.get("styles", {}) or {}).get("css") or ""
        if css.strip():
            theme_css[slug] = css

    if len(theme_css) < 2:
        r.skip(
            f"need >=2 themes loaded to compare chrome; found {len(theme_css)} "
            f"({', '.join(sorted(theme_css)) or 'none'})."
        )
        return r

    failures: list[str] = []
    verified: list[str] = []

    for selector in DISTINCT_CHROME_SELECTORS:
        # Bucket themes by their base rule body for this selector.
        clusters: dict[str, list[str]] = {}
        skipped_themes: list[str] = []
        for slug, css in sorted(theme_css.items()):
            body = _find_base_rule_body(css, selector)
            if body is None:
                # No base rule for this selector in this theme — that's
                # fine; the theme just doesn't paint this surface yet.
                skipped_themes.append(slug)
                continue
            clusters.setdefault(body, []).append(slug)

        cluster_failed = False
        for body, slugs in clusters.items():
            if len(slugs) < 2:
                continue
            # Cluster of 2+ themes sharing one base body. Each theme in
            # the cluster must provide its OWN per-theme override.
            offenders = [
                slug
                for slug in slugs
                if not _has_per_theme_override(theme_css[slug], slug, selector)
            ]
            if len(offenders) < 2:
                # At most one theme leans on the shared base — every
                # other one in the cluster has overridden it.
                continue
            cluster_failed = True
            failures.append(
                f"`{selector}`: themes [{', '.join(offenders)}] ship "
                f"byte-identical base CSS with no `body.theme-<slug> "
                f"{selector.split(',')[0]}` override. Either (a) author "
                f"a different base rule body in one of the themes' "
                f"`styles.css` / `styles.blocks`, or (b) add per-theme "
                f"distinctive overrides in `bin/append-wc-overrides.py` "
                f"Phase E/F so every theme expresses its own voice on "
                f"this surface. Shared 'standard' chrome is what makes "
                f"WooCommerce demos read as off-the-shelf — see AGENTS.md "
                f"\"Nothing is 'standard'\"."
            )

        if not cluster_failed:
            covered = sorted(theme_css)
            if skipped_themes:
                covered = [s for s in covered if s not in skipped_themes]
            verified.append(f"`{selector}` distinct across [{', '.join(covered)}]")

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if verified:
        for v in verified:
            r.details.append(v)
    else:
        r.skip("no DISTINCT_CHROME_SELECTORS rules present in any theme yet")
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

    template_paths = (
        sorted((ROOT / "templates").glob("archive-product*.html"))
        if (ROOT / "templates").exists()
        else []
    )
    triggering = next(
        (
            p
            for p in template_paths
            if re.search(
                r"<!--\s*wp:woocommerce/catalog-sorting(?:\s|/|-->)",
                p.read_text(encoding="utf-8", errors="replace"),
            )
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
            f'class="orderby">`) but top-level `styles.css` never '
            f"targets `.wp-block-woocommerce-catalog-sorting select.orderby` "
            f"or `.woocommerce-ordering select.orderby`. Shoppers see the "
            f'OS-native dropdown — the loudest "default WooCommerce theme" '
            f"tell on a shop archive. Add a rule like "
            f"`.wp-block-woocommerce-catalog-sorting select.orderby,"
            f".woocommerce-ordering select.orderby {{ appearance:none; "
            f"-webkit-appearance:none; ... }}` to top-level `styles.css`. "
            f'Block-scoped `styles.blocks["woocommerce/catalog-sorting"]'
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
        missing = (
            "legacy `.woocommerce-ordering`"
            if has_block_sel
            else "block `.wp-block-woocommerce-catalog-sorting`"
        )
        r.details.append(
            f"WARNING: only one selector root present; consider also "
            f"covering the {missing} root so shortcode-driven catalogs "
            f"render the same dropdown."
        )
    r.details.append("matched dropdown selector + `appearance:none` in top-level styles.css")
    return r


def check_cart_checkout_pages_are_wide() -> Result:
    """Guard against the cart/checkout `contentSize` squeeze regression.

    `templates/page.html` constrains `wp:post-content` to
    `contentSize:var(--wp--custom--layout--prose)` (~560px) so blog and
    long-form prose pages get an editorial measure. Without an explicit
    `align:wide` on the seeded `wp:woocommerce/cart` and
    `wp:woocommerce/checkout` root blocks, the entire two-column layout
    inherits the 560px prose container at every viewport width.

    Symptom (caught in production review on 2026-04-20):
      * Tablet (<782px viewport): the responsive grid stacks to a
        single column inside the 560px container, so the squeeze is
        invisible.
      * Desktop (>=782px viewport): the grid kicks in inside that same
        560px container -> sidebar takes 300-360px and the form
        column collapses to ~200-260px. Order-summary item content
        ("Artisanal Silence (8 oz Jar)") wraps per-letter again,
        exactly the bug `check_no_squeezed_wc_sidebars` was supposed
        to prevent. CSS alone could not fix it because the container
        itself is the wrong width.

    Fix lives in two places now:
      * Cart root block: `<theme>/patterns/cart-page.php`
        (`Block Types: woocommerce/cart`). `wo-configure.php`
        `include`s the pattern with output buffering so its
        translated block tree becomes the Cart page `post_content`.
      * Checkout root block: still inlined in `wo-configure.php`
        (no per-theme microcopy on Checkout — the brand work lives
        on the Cart page).

    Both root blocks carry `{"align":"wide"}` so they opt out of the
    prose contentSize and use the theme's wideSize (1280px) instead.
    At 1280px the 1fr / minmax(300px,360px) grid breathes correctly:
    ~880px form, ~360px sidebar.

    This rule asserts the markers are present in the per-theme cart
    pattern (Cart) and in the inlined `wo-configure.php` of the
    theme's `playground/blueprint.json` (Checkout).
    """
    r = Result("Cart/Checkout root blocks are align:wide")
    bp_path = ROOT / "playground" / "blueprint.json"
    if not bp_path.exists():
        r.skip("no playground/blueprint.json (theme without a Playground blueprint)")
        return r
    try:
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"playground/blueprint.json: invalid JSON ({exc}).")
        return r

    # Cart side: read the per-theme pattern file directly. The pattern
    # is the source of truth for the cart block tree (wo-configure.php
    # `include`s it via output buffering; see § 11d). Reading the file
    # rather than re-parsing the blueprint lets the gate fire even if
    # the blueprint hasn't been re-synced after a pattern edit.
    cart_pattern_path = ROOT / "patterns" / "cart-page.php"
    cart_src = ""
    if cart_pattern_path.is_file():
        cart_src = cart_pattern_path.read_text(encoding="utf-8")
    else:
        r.fail(
            "patterns/cart-page.php missing — wo-configure.php § 11d "
            "reads this file via include + ob_start to seed the Cart "
            "page. Without it the demo Cart renders WC default chrome."
        )

    # Checkout side: still inlined in wo-configure.php. sync-playground.py
    # emits it as a `writeFile` step at `wp-content/mu-plugins/wo-configure.php`.
    cfg_data: str | None = None
    for step in bp.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        if step.get("step") != "writeFile":
            continue
        path = step.get("path") or ""
        if "wo-configure.php" not in path:
            continue
        data = step.get("data")
        if isinstance(data, str):
            cfg_data = data
            break

    if cfg_data is None:
        # No inlined wo-configure.php means the blueprint either uses a
        # different content-seeding strategy or hasn't been synced. Either
        # way this rule cannot validate the checkout block markup.
        r.skip("no inlined wo-configure.php in blueprint (run bin/sync-playground.py)")
        return r

    required = [
        (
            cart_src,
            'wp:woocommerce/cart {"align":"wide"}',
            "patterns/cart-page.php",
            "Cart root block (`wp:woocommerce/cart`) is missing "
            '`{"align":"wide"}` in patterns/cart-page.php. Without it '
            "the cart inherits `contentSize:prose` (~560px) from "
            "`templates/page.html` and the sidebar collapses on desktop, "
            "producing per-letter text wrapping in the totals column.",
        ),
        (
            cfg_data,
            'wp:woocommerce/checkout {"align":"wide"}',
            "playground/wo-configure.php (inlined into blueprint)",
            "Checkout root block (`wp:woocommerce/checkout`) is missing "
            '`{"align":"wide"}` in inlined wo-configure.php. Without it '
            "the checkout inherits `contentSize:prose` (~560px) from "
            "`templates/page.html` and the order-summary sidebar collapses "
            "on desktop, producing per-letter wraps of product names like "
            "'Artisanal Silence'.",
        ),
    ]
    for src, needle, where, message in required:
        if src and needle not in src:
            r.fail(f"{where}: {message}")

    # Belt and suspenders: the rendered wrapper div must also carry
    # `alignwide` so the front-end CSS picks up the wide-width rules.
    # WordPress derives the class from the block attribute, but the
    # cart pattern + checkout heredoc write the wrapper div by hand;
    # if the editor ever re-saves the page the class will be regenerated
    # correctly, but the seeded source must already match so first
    # paint is correct.
    div_required = [
        (
            cart_src,
            "wp-block-woocommerce-cart alignwide",
            "patterns/cart-page.php",
            "Cart wrapper div is missing the `alignwide` class. The wrapper "
            'must read `<div class="wp-block-woocommerce-cart alignwide is-loading">` '
            "to match the `align:wide` block attribute on first render.",
        ),
        (
            cfg_data,
            "wp-block-woocommerce-checkout alignwide",
            "playground/wo-configure.php (inlined into blueprint)",
            "Checkout wrapper div is missing the `alignwide` class. The wrapper "
            'must read `<div class="wp-block-woocommerce-checkout alignwide wc-block-checkout is-loading">` '
            "to match the `align:wide` block attribute on first render.",
        ),
    ]
    for src, needle, where, message in div_required:
        if src and needle not in src:
            r.fail(f"{where}: {message}")

    if r.passed and not r.skipped:
        r.details.append(
            "verified `align:wide` on cart root block + wrapper div in "
            "patterns/cart-page.php, and on checkout root block + "
            "wrapper div in inlined wo-configure.php"
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
            '`"/"` so the bare blueprint opens the designed homepage '
            "(not WP's default `/wp-admin/` landing). The docs/<theme>/ "
            "redirector forces `&url=/` already, but the blueprint is "
            "consumed standalone too (drag-and-drop, blueprint editor, "
            "third-party launchers)."
        )
    elif landing != "/":
        r.fail(
            f"playground/blueprint.json: `landingPage` is "
            f'`{json.dumps(landing)}`, expected `"/"`. The repo\'s '
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
        other_fp = _front_page_fingerprint(other_fp_path.read_text(encoding="utf-8"))
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


def check_pdp_has_image() -> Result:
    """Fail if a single-product template has no PDP image block.

    PDP IMAGE FAIL MODE
    -------------------
    The single-product template originally rendered the WC image gallery via
    `wp:woocommerce/product-image-gallery`. The block depends on
    Flexslider + PhotoSwipe wiring at runtime; on Playground (and on a fresh
    WC install where the gallery JS hasn't initialised yet) the markup
    sometimes paints as a single empty cream-coloured box with a
    magnifying-glass icon overlay — the worst possible "PDP that's broken"
    tell on the demo.

    Phase A migrates every theme's single-product PDP to render the image
    via `wp:post-featured-image` instead, which is a server-rendered img
    tag with no JS dependency. To make sure that swap is locked in we
    require the template to render AT LEAST ONE of:

        wp:post-featured-image
        wp:woocommerce/product-image-gallery
        wp:woocommerce/product-image
        wp:woocommerce/product-gallery

    If `wp:woocommerce/product-image-gallery` is the only image block, we
    issue a warning (it's the regression-prone path); the check passes
    because some themes legitimately need it (e.g. for the lightbox).

    See AGENTS.md hard rule "PDP must always have a product image".
    """
    r = Result("PDP single-product template renders a product image block")
    template_paths = [
        ROOT / "templates" / "single-product.html",
        ROOT / "templates" / "single-product-variable.html",
    ]
    template_paths = [p for p in template_paths if p.exists()]
    if not template_paths:
        r.skip("no single-product template found in this theme")
        return r

    image_blocks = (
        "wp:post-featured-image",
        "wp:woocommerce/product-image-gallery",
        "wp:woocommerce/product-image",
        "wp:woocommerce/product-gallery",
    )
    for path in template_paths:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(b in text for b in image_blocks):
            r.fail(
                f"{rel} renders no product image block. PDPs without an "
                f'image are the loudest "this site is broken" tell on '
                f"the demo. Add one of: `wp:post-featured-image` "
                f"(preferred — server-rendered, no JS dependency), "
                f"`wp:woocommerce/product-image-gallery` (legacy — "
                f"depends on Flexslider/PhotoSwipe init), "
                f"`wp:woocommerce/product-image`, or "
                f"`wp:woocommerce/product-gallery`."
            )
            continue
        # If only the legacy gallery block is present, surface that as a
        # detail line so a human reviewer can decide whether to swap to
        # post-featured-image. This is informational, not a fail.
        if (
            "wp:woocommerce/product-image-gallery" in text
            and "wp:post-featured-image" not in text
            and "wp:woocommerce/product-image" not in text
            and "wp:woocommerce/product-gallery" not in text
        ):
            r.details.append(
                f"WARNING: {rel} renders ONLY "
                f"`wp:woocommerce/product-image-gallery`. That block "
                f"sometimes fails to initialise its Flexslider/PhotoSwipe "
                f"JS on Playground and paints as an empty cream box with "
                f"a magnifying-glass icon. Consider swapping to "
                f"`wp:post-featured-image` (server-rendered, no JS)."
            )
    if r.passed and not r.skipped and not r.details:
        r.details.append(f"{len(template_paths)} template(s) checked")
    return r


# Pattern microcopy strings shorter than this are treated as labels
# (e.g. "Shop", "Returns", "Privacy", "Read more", "Read the journal")
# and ignored — they're conventional wayfinding text every store needs
# and re-using them across themes is normal. Anything longer is body
# copy or a headline that must be rewritten in the theme's own voice.
PATTERN_MICROCOPY_MIN_CHARS = 20

# Translatable string call-sites we scan inside patterns/*.php. We
# deliberately exclude the `esc_attr_*` family because those wrap
# alt-text / aria-label / title attributes, which describe the same
# image or icon across themes and SHOULD match by design (an image of
# a coral-linen-tagged glass bottle is a coral-linen-tagged glass bottle
# regardless of the theme's voice).
#
# The string-body subpattern `(?:\\.|(?!\1).)*` skips over backslash-
# escaped characters (e.g. `\'` inside a single-quoted PHP string)
# instead of stopping at the first inner quote. The earlier regex used
# a non-greedy `.*?` which truncated at the first `\'`, so strings like
# `'What if it doesn\'t fit right?'` extracted as just `What if it
# doesn\` and silently collided across themes that all happened to
# start with the same eight letters. Handle escapes properly.
PATTERN_MICROCOPY_RE = re.compile(
    r"""(?<![A-Za-z0-9_])(?:esc_html_e|esc_html__|_e|__)\s*\(\s*(['"])((?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)


def _extract_pattern_microcopy(patterns_dir: Path) -> dict[str, set[str]]:
    """Map basename → set of long user-facing strings inside each pattern.

    We bucket per-file so the failure message can tell you exactly which
    pattern in the current theme still ships the obel default for the
    same-named pattern.
    """
    out: dict[str, set[str]] = {}
    if not patterns_dir.is_dir():
        return out
    for php in sorted(patterns_dir.glob("*.php")):
        text = php.read_text(encoding="utf-8", errors="ignore")
        strings = {
            m.group(2)
            for m in PATTERN_MICROCOPY_RE.finditer(text)
            if len(m.group(2)) >= PATTERN_MICROCOPY_MIN_CHARS
        }
        if strings:
            out[php.name] = strings
    return out


# Heading content extracted from `<!-- wp:heading {...content":"..."} -->`
# delimiters in template / part HTML files. We treat heading copy with
# the same distinctness rule as pattern microcopy: the same headline
# appearing on two different themes is a "this is the same theme with
# a different paint job" tell.
TEMPLATE_HEADING_RE = re.compile(
    r'<!--\s*wp:heading\s+(\{[^}]*?"content"\s*:\s*"((?:\\"|[^"])*)"[^}]*?\})\s*/?-->',
    re.DOTALL,
)


def _normalize_heading(s: str) -> str:
    """Lowercase + collapse whitespace + strip trailing punctuation so
    "Field notes", "Field notes.", and "Field notes from the workshop"
    all share a comparable normalised core. We keep the words intact;
    the substring/word-overlap test runs on the normalised form."""
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s.rstrip(".,;:!?— -")


# Generic wayfinding headings every store needs. These appear on every
# theme by design and should NOT trip the "shared microcopy" check.
# Anything outside this allowlist is treated as voice / brand copy.
SHARED_HEADING_ALLOWLIST = frozenset(
    {
        "shop",
        "categories",
        "cart",
        "checkout",
        "account",
        "my account",
        "log in",
        "register",
        "search results",
        "404",
        "page not found",
        "shop by category",
        "featured products",
        "new arrivals",
        "on sale",
        "related products",
        "you may also like",
        "your cart",
        "order summary",
        "billing",
        "shipping",
        "payment",
        "order details",
    }
)


def _extract_template_headings(theme_dir: Path) -> dict[str, set[str]]:
    """Map relative file path → set of normalised heading copy strings
    found in template + part HTML (excludes wayfinding allowlist)."""
    out: dict[str, set[str]] = {}
    for sub in ("templates", "parts"):
        d = theme_dir / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.html")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            headings: set[str] = set()
            for m in TEMPLATE_HEADING_RE.finditer(text):
                raw = m.group(2).encode("utf-8").decode("unicode_escape", errors="ignore")
                norm = _normalize_heading(raw)
                # Keep headings 4+ chars that aren't pure wayfinding.
                if len(norm) >= 4 and norm not in SHARED_HEADING_ALLOWLIST:
                    headings.add(norm)
            if headings:
                out[path.relative_to(theme_dir).as_posix()] = headings
    return out


def check_pattern_microcopy_distinct() -> Result:
    """Fail when patterns OR template/part headings ship copy that
    overlaps with another theme's same-named pattern, or whose heading
    string is shared (or contained-within / containing) another theme's
    heading.

    Why this exists
    ---------------
    Two failure modes are unmistakable "this is the same theme with a
    different paint job" tells on the live demo:

    (a) `bin/clone.py` copies obel's patterns into every new theme,
        rewriting only the slug + textdomain. Without a follow-up pass
        the new theme inherits obel's placeholder microcopy ("A short
        statement of intent.", "Two or three sentences explaining why
        your brand exists...") and ships it in production.

    (b) An author drops a heading like "Field notes" onto a theme's
        front-page section without realising another theme already
        owns that phrase ("Field notes from the workshop." in
        selvedge's footer). Even a partial overlap reads as a borrowed
        voice on a side-by-side demo browse.

    What this check enforces
    ------------------------
    PATTERNS: pairwise across every theme — for each pattern file in
    the current theme, compare its translatable strings ≥
    PATTERN_MICROCOPY_MIN_CHARS chars to the same-named pattern in
    every other theme. Fail on any byte-identical match.

    TEMPLATE/PART HEADINGS: pairwise across every theme — for each
    `wp:heading` in templates/ and parts/, normalise (lowercase,
    collapse whitespace, strip trailing punctuation), drop wayfinding
    allowlist items ("Shop", "Cart", "My Account", …), then fail on
    any (a) byte-identical normalised heading shared with another
    theme, or (b) word-substring overlap where one heading wholly
    contains the other and BOTH are 2+ words.

    The fix is always the same: rewrite the offending string in the
    theme's own brand voice. The check fires per-string so you can see
    exactly which copy is being shared.
    """
    r = Result("Pattern + heading microcopy distinct across themes")

    theme_slug = ROOT.name
    theme_patterns = _extract_pattern_microcopy(ROOT / "patterns")
    theme_headings = _extract_template_headings(ROOT)

    if not theme_patterns and not theme_headings:
        r.skip("no patterns/*.php and no headings in templates/ or parts/")
        return r

    # PATTERN-vs-PATTERN: pairwise across every other theme.
    for other in iter_themes():
        other_slug = other.name
        if other_slug == theme_slug:
            continue
        other_patterns = _extract_pattern_microcopy(other / "patterns")
        if not other_patterns:
            continue
        for fname, strings in sorted(theme_patterns.items()):
            other_set = other_patterns.get(fname, set())
            if not other_set:
                continue
            for s in sorted(strings & other_set):
                short = s if len(s) <= 80 else s[:77] + "..."
                r.fail(
                    f"patterns/{fname}: ships microcopy verbatim shared "
                    f"with {other_slug}/patterns/{fname} — "
                    f'"{short}" — rewrite in {theme_slug}\'s voice'
                )

    # HEADING-vs-HEADING: pairwise across every other theme. We compare
    # the union of every heading in the current theme against the union
    # of every heading in each other theme (NOT same-file matched —
    # "Field notes" in aero front-page collides with "Field notes from
    # the workshop" in selvedge footer).
    if theme_headings:
        my_all = set().union(*theme_headings.values())
        for other in iter_themes():
            other_slug = other.name
            if other_slug == theme_slug:
                continue
            other_headings = _extract_template_headings(other)
            if not other_headings:
                continue
            other_all = set().union(*other_headings.values())

            for h in sorted(my_all):
                # (a) byte-identical normalised heading shared.
                if h in other_all:
                    rel = next(
                        (rel for rel, hs in theme_headings.items() if h in hs),
                        "?",
                    )
                    r.fail(
                        f'{rel}: ships heading "{h}" shared verbatim '
                        f"with {other_slug} — rewrite in {theme_slug}'s "
                        f"voice (every theme on the demo browse should "
                        f"speak in its own voice end-to-end)"
                    )
                    continue
                # (b) word-overlap: one heading wholly contains the
                # other AND both are 2+ words AND the shared core is
                # 2+ words. This catches "Field notes" ⊂ "Field notes
                # from the workshop." but doesn't fire on single-word
                # accidents like "Featured" ⊂ "Featured products".
                my_words = h.split()
                if len(my_words) < 2:
                    continue
                for o in other_all:
                    o_words = o.split()
                    if len(o_words) < 2:
                        continue
                    # Require a contiguous 2+ word phrase shared.
                    shared = _longest_shared_phrase(my_words, o_words)
                    if shared and len(shared.split()) >= 2:
                        rel = next(
                            (rel for rel, hs in theme_headings.items() if h in hs),
                            "?",
                        )
                        r.fail(
                            f'{rel}: heading "{h}" shares the phrase '
                            f'"{shared}" with {other_slug}\'s heading '
                            f'"{o}" — pick a phrase no other theme is '
                            f"already using"
                        )
                        break

    if r.passed and not r.skipped:
        r.details.append(
            f"{len(theme_patterns)} pattern file(s) + "
            f"{len(theme_headings)} template/part file(s) with headings; "
            f"all microcopy distinct vs every other theme"
        )
    return r


# ---------------------------------------------------------------------------
# Comprehensive cross-theme rendered-text distinctness check.
#
# `check_pattern_microcopy_distinct` only looks at:
#   - PHP `__()/_e()/...` strings inside patterns/*.php
#   - `wp:heading` block delimiters in templates/parts
#
# That's a small slice of what the demo actually paints. Every paragraph,
# button label, list item, blockquote, verse, pullquote, footer
# copyright, eyebrow strap, FAQ question, hero subtitle, and care-copy
# block also reads on a side-by-side demo browse — and `bin/clone.py`
# copies them verbatim from obel into every new theme. The audit script
# below documents what we found before this gate was added: 39 distinct
# strings duplicated across 2–5 themes. The check below scans EVERY
# rendered text surface so the same regression can't reach the demo
# again.
#
# Scanned surfaces (in templates/, parts/, patterns/):
#   - block delimiter `"content":"…"` for any of:
#       wp:heading, wp:paragraph, wp:button, wp:list-item, wp:verse,
#       wp:pullquote, wp:preformatted
#   - inner text inside any block-rendered `<h1-6>`, `<p>`, `<li>`,
#     `<button>`, `<a>`, `<figcaption>`, `<blockquote>` tag
#   - PHP `__()/_e()/esc_html_e()/esc_html__()/esc_attr_e()/esc_attr__()`
#     literals inside *.php
# ---------------------------------------------------------------------------

ALL_TEXT_MIN_CHARS = 12

ALL_TEXT_BLOCK_DELIMITER_RE = re.compile(
    r"<!--\s*wp:(?:heading|paragraph|button|list-item|verse|pullquote|preformatted)\s+"
    r'(\{[^}]*?"content"\s*:\s*"((?:\\.|[^"\\])*)"[^}]*?\})\s*/?-->',
    re.DOTALL,
)

ALL_TEXT_INNER_HTML_RE = re.compile(
    r"<(?:h[1-6]|p|li|figcaption|blockquote|button|a)[^>]*>([^<]{4,})"
    r"</(?:h[1-6]|p|li|figcaption|blockquote|button|a)>"
)

ALL_TEXT_PHP_TX_RE = re.compile(
    r"""(?<![A-Za-z0-9_])(?:esc_html_e|esc_html__|esc_attr_e|esc_attr__|_e|__)\s*\(\s*"""
    r"""(['"])((?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)

# Generic wayfinding / system text every store needs end-to-end. Each
# entry must already be normalised (lowercased, whitespace collapsed,
# trailing punctuation stripped) — see `_normalize_for_text_audit`.
ALL_TEXT_ALLOWLIST = frozenset(
    {
        # short imperatives + nav (most are <12 chars and won't reach the
        # check anyway, but we list them defensively)
        "shop",
        "cart",
        "checkout",
        "account",
        "my account",
        "log in",
        "login",
        "register",
        "search",
        "menu",
        "home",
        "about",
        "contact",
        "blog",
        "journal",
        "read more",
        "view all",
        "view cart",
        "add to cart",
        "shop all",
        "shop now",
        "learn more",
        "all",
        "next",
        "previous",
        "back",
        "close",
        "open",
        "submit",
        "subscribe",
        "newsletter",
        "instagram",
        "twitter",
        "facebook",
        "pinterest",
        "tiktok",
        "returns",
        "shipping",
        "help",
        "faq",
        "support",
        "press",
        "careers",
        "company",
        "product",
        "products",
        "collection",
        "collections",
        "categories",
        "category",
        # 404 / search empty states
        "page not found",
        "search results",
        "no results",
        "no posts",
        # cart / checkout system labels
        "continue shopping",
        "order summary",
        "subtotal",
        "total",
        "tax",
        "discount",
        "view details",
        "see details",
        "read the journal",
        "read the story",
        # short attribute / image labels often shared by design (alt-text,
        # status pills, etc.)
        "in stock",
        "out of stock",
        "free",
        "sold out",
        "on sale",
    }
)


def _normalize_for_text_audit(s: str) -> str:
    """Lowercase, collapse whitespace, strip HTML tags, strip trailing
    punctuation. Mirrors `_normalize_heading` but also drops PHP-source
    backslash-escaped quotes and common JSON-encoded characters."""
    s = s.replace("\\'", "'").replace('\\"', '"')
    s = s.replace("\\u2019", "'").replace("\\u2014", "—").replace("\\u2013", "–")
    s = s.replace("\\n", " ").replace("\\/", "/")
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower().rstrip(".,;:!?— -")


def _extract_all_rendered_text(theme_dir: Path) -> dict[str, set[str]]:
    """Map normalised user-visible text → set of "{rel}::{raw}" tags.

    We collect every text fragment a visitor would see end-to-end:
    block-delimiter content, inner HTML text, and PHP translatable
    literals. Any fragment whose normalised form is < ALL_TEXT_MIN_CHARS
    or appears in the wayfinding allowlist is dropped — those are
    expected to repeat across themes by design.
    """
    out: dict[str, set[str]] = {}
    for sub in ("templates", "parts", "patterns"):
        d = theme_dir / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*")):
            if not path.is_file() or path.suffix not in {".html", ".php"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = path.relative_to(theme_dir).as_posix()

            fragments: list[str] = []
            for m in ALL_TEXT_BLOCK_DELIMITER_RE.finditer(text):
                # Block-attribute JSON values are unicode-escaped; decode
                # so smart quotes / em-dashes normalise the same way as
                # the inner-HTML form of the same string.
                raw = m.group(2)
                try:
                    raw = raw.encode("utf-8").decode("unicode_escape", errors="ignore")
                except Exception:
                    pass
                fragments.append(raw)
            for m in ALL_TEXT_INNER_HTML_RE.finditer(text):
                fragments.append(m.group(1))
            if path.suffix == ".php":
                for m in ALL_TEXT_PHP_TX_RE.finditer(text):
                    fragments.append(m.group(2))

            for raw in fragments:
                norm = _normalize_for_text_audit(raw)
                if len(norm) < ALL_TEXT_MIN_CHARS:
                    continue
                if norm in ALL_TEXT_ALLOWLIST:
                    continue
                out.setdefault(norm, set()).add(rel)
    return out


def check_all_rendered_text_distinct_across_themes() -> Result:
    """Fail when ANY rendered text fragment in this theme appears
    verbatim (after case-insensitive whitespace normalisation) in
    another theme.

    Why this exists
    ---------------
    `check_pattern_microcopy_distinct` only inspects PHP translatable
    strings inside patterns/*.php and the `content` attribute of
    `wp:heading` block delimiters. That misses the long tail of copy
    that actually paints on the demo:

        - paragraph body text (`wp:paragraph`)
        - button labels (`wp:button`, plain `<a class=…__link>`)
        - list items, blockquotes, verses, pullquotes, preformatted
        - eyebrow / strap paragraphs
        - footer copyright lines
        - 404 / no-results / coming-soon body copy
        - order-confirmation step lists ("01 — Confirmation", …)
        - care + shipping policy paragraphs on PDPs

    A single audit pass against every theme on this branch found 39
    such duplicate strings, all originating from `bin/clone.py` copying
    obel verbatim into the new theme without a follow-up voice pass.
    The result reads on a side-by-side demo browse as one shop in
    different paint jobs — exactly the failure mode the project goes
    out of its way to avoid.

    What this check enforces
    ------------------------
    For every theme, walk templates/, parts/, patterns/. From each
    *.html and *.php file, extract:

        (1) every `"content":"…"` value inside a wp:heading,
            wp:paragraph, wp:button, wp:list-item, wp:verse,
            wp:pullquote, or wp:preformatted block delimiter,
        (2) every inner-text run inside a block-rendered <h1-6>, <p>,
            <li>, <button>, <a>, <figcaption>, or <blockquote> tag,
        (3) every PHP `__()/_e()/esc_html_e()/esc_html__()/
            esc_attr_e()/esc_attr__()` literal in *.php files.

    Normalise (lowercase, collapse whitespace, strip trailing
    punctuation, decode JSON unicode escapes and PHP backslash escapes,
    strip inline tags). Drop fragments shorter than
    ALL_TEXT_MIN_CHARS (12 chars) and any fragment in
    ALL_TEXT_ALLOWLIST (functional wayfinding text every store needs).

    Then for every remaining fragment in this theme, fail if the same
    normalised fragment appears in any other theme's surface.

    Fix path
    --------
    Two options when this fires:
      1. If the duplicate is intentional functional / system text,
         add it to ALL_TEXT_ALLOWLIST above (with a comment).
      2. Otherwise, rewrite the offending fragment in this theme's
         own brand voice. `bin/personalize-microcopy.py` holds the
         per-theme substitution map used to clean up the original
         clone-and-skin debt — extend that map and re-run, or edit
         the file directly.
    """
    r = Result("All rendered text distinct across themes")

    theme_slug = ROOT.name
    my_text = _extract_all_rendered_text(ROOT)
    if not my_text:
        r.skip("no templates/, parts/, or patterns/ with rendered text")
        return r

    # Build other-theme index lazily — once per other theme, not once
    # per fragment. Keys are normalised text; values are
    # {theme_slug: {rel_paths}}.
    other_index: dict[str, dict[str, set[str]]] = {}
    for other in iter_themes():
        other_slug = other.name
        if other_slug == theme_slug:
            continue
        for norm, rels in _extract_all_rendered_text(other).items():
            other_index.setdefault(norm, {})[other_slug] = rels

    collisions = 0
    for norm in sorted(my_text):
        if norm not in other_index:
            continue
        my_rel = next(iter(sorted(my_text[norm])))
        for other_slug, other_rels in sorted(other_index[norm].items()):
            other_rel = next(iter(sorted(other_rels)))
            shown = norm if len(norm) <= 100 else norm[:97] + "..."
            r.fail(
                f"{my_rel}: ships rendered text shared verbatim with "
                f'{other_slug}/{other_rel} — "{shown}" — rewrite in '
                f"{theme_slug}'s voice (or add to ALL_TEXT_ALLOWLIST "
                f"if it's truly system / wayfinding copy)"
            )
            collisions += 1

    if r.passed and not r.skipped:
        r.details.append(
            f"{len(my_text)} text fragment(s) scanned across "
            f"templates/, parts/, patterns/; all distinct vs every "
            f"other theme"
        )
    return r


def _longest_shared_phrase(a: list[str], b: list[str]) -> str:
    """Longest contiguous shared word-sequence between two heading word
    lists, normalised. Returns empty string if no overlap."""
    best = ""
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > 0:
                phrase = " ".join(a[i : i + k])
                if len(phrase) > len(best):
                    best = phrase
    return best


def check_no_default_wc_strings() -> Result:
    """Fail if a theme's functions.php doesn't ship every canonical
    default-WC microcopy override.

    DEFAULT-WC-STRING FAIL MODE
    ---------------------------
    Even after Phases A–E reskin every WC surface, four or five strings
    on the cart, account login, and shop archive are unmistakable
    "this is a stock WooCommerce install" tells:

        - "Showing 1-16 of 55 results"  (loop result count)
        - "Default sorting"             (catalog-sorting first option)
        - "Estimated total"             (cart totals label)
        - "Proceed to Checkout"         (order-button text)
        - "Lost your password?"         (account form link)

    Since the theme-shipped microcopy refactor, every theme owns its
    own override block bracketed by `// === BEGIN wc microcopy ===`
    sentinels at the bottom of `<theme>/functions.php`. The block
    rewrites those strings in that theme's brand voice. This check
    asserts both halves: the sentinel block is present, AND each of
    the canonical override fragments survives inside it. Drop the
    block and the live demo paints with stock WC strings; drop a
    fragment and the matching surface regresses individually.

    The check is per-theme because the override block is per-theme
    (each theme has its own voice + text domain). The previous
    iteration scanned the inlined mu-plugin in blueprint.json; that
    mu-plugin was deleted because shopper-facing brand must travel
    with the released theme, not be bolted on by a Playground-only
    must-use plugin.

    See AGENTS.md hard rule "No default WC strings on the live demo".
    """
    r = Result("Default WC microcopy is overridden in <theme>/functions.php")
    fn_path = ROOT / "functions.php"
    if not fn_path.exists():
        r.skip("no functions.php (theme without PHP bootstrap)")
        return r

    src = fn_path.read_text(encoding="utf-8")
    begin = "// === BEGIN wc microcopy ==="
    end = "// === END wc microcopy ==="
    if begin not in src or end not in src:
        r.fail(
            "functions.php has no `// === BEGIN wc microcopy === ... "
            "// === END wc microcopy ===` block. The live demo will "
            "paint with WC's default strings (\"Showing 1-16 of 55 "
            'results", "Default sorting", "Estimated total", '
            '"Proceed to Checkout", "Lost your password?"). Append '
            "the canonical block to `functions.php` (see obel/functions.php "
            "for the reference shape) — it MUST live in the theme so the "
            "overrides ship when the theme is dropped into wp-content/themes/."
        )
        return r

    block = src[src.index(begin) : src.index(end) + len(end)]

    # Each entry: a fragment of the override that MUST appear in the
    # block, plus the user-facing default string it displaces. Fragments
    # are intentionally narrow (the WP filter hook name or the literal
    # WC default string in the gettext map) so a future refactor that
    # splits the filter into multiple closures still works as long as
    # the displaced string still gets replaced.
    required = [
        ("woocommerce_blocks_cart_totals_label", '"Estimated total" cart totals label'),
        ("woocommerce_order_button_text", '"Proceed to Checkout" / "Place order" button text'),
        (
            "woocommerce_default_catalog_orderby_options",
            '"Default sorting" catalog-sorting first option',
        ),
        ("Lost your password?", '"Lost your password?" account login link'),
        (
            "render_block_woocommerce/product-results-count",
            '"Showing 1-16 of 55 results" loop result count '
            "(rewritten in place via render_block filter — a "
            "woocommerce_before_shop_loop echo would produce a duplicate "
            "floating count inside wp:woocommerce/product-collection)",
        ),
    ]
    for needle, label in required:
        if needle not in block:
            r.fail(
                f"functions.php wc microcopy block is missing the override "
                f"for {label} (looked for `{needle}` between the BEGIN/END "
                f"sentinels). The default string will paint on the live demo."
            )

    if r.passed and not r.skipped:
        r.details.append(
            f"all {len(required)} default-WC microcopy overrides "
            f"present in functions.php wc microcopy block"
        )
    return r


def check_no_brand_filters_in_playground() -> Result:
    """Forbid shopper-facing brand filters in any `playground/*.php`.

    BRAND-IN-PLAYGROUND FAIL MODE
    -----------------------------
    The `playground/` directory is for boot-time setup that has no
    analogue on a real WordPress install: WXR import, WC catalogue
    seeding, demo cart pre-fill, swatch markup, payment-icon strip.
    Anything that affects what a real shopper sees on a released theme
    MUST live in the theme directory (`<theme>/functions.php`,
    templates, parts, patterns, `theme.json`, `styles/`, `style.css`)
    so the override travels with the theme when a Proprietor downloads
    it and drops it into `wp-content/themes/`.

    Before the theme-shipped microcopy refactor, `wo-microcopy-mu.php`
    in `playground/` registered ~12 filters that affected exactly that
    surface area: cart/checkout `gettext` map, sort labels, pagination
    arrows, result-count rewrite, WC Blocks button text, required-field
    marker swap. The mu-plugin was inlined into every blueprint and
    nothing else; release-only consumers got bare WC default strings.
    The fix moved every filter into `<theme>/functions.php` and
    deleted the mu-plugin. This check guarantees no future regression:
    if any `add_filter` / `add_action` registered against a known
    brand-affecting hook reappears in `playground/*.php`, the gate
    fails, names the file, names the hook, and points at the rule.

    The denylist is conservative on purpose. Hooks that legitimately
    only matter at boot (`init`, `wp_loaded`, `woocommerce_init`,
    `woocommerce_loaded`, `pre_get_posts` for the seed step, etc.)
    are never on it; only hooks that change a string a shopper reads
    or HTML a shopper sees are denied.

    Allowlist: a forbidden hook may be registered if its `add_filter`
    call sits inside an `if ( defined('WO_DEMO_ONLY') )` (or any
    `defined('WO_*')` constant) guard, so a future genuine demo-only
    override can opt out of the rule explicitly. The check looks for
    `defined(` within 200 chars before the `add_filter` call.

    See AGENTS.md root-rule "Shopper-facing brand lives in the theme,
    not in playground/".
    """
    r = Result("playground/*.php registers no shopper-facing brand filters")
    pg_dir = MONOREPO_ROOT / "playground"
    if not pg_dir.is_dir():
        r.skip("no playground/ directory")
        return r

    # Hooks whose every callback rewrites a string a shopper reads
    # (gettext family, WC Blocks React strings, sort labels, page-title
    # visibility) or HTML a shopper sees (form-field marker, archive
    # result-count rewrite, pagination arrows). Wildcards are matched
    # by prefix.
    forbidden_exact = {
        "gettext",
        "gettext_with_context",
        "ngettext",
        "ngettext_with_context",
        "woocommerce_form_field",
        "woocommerce_default_catalog_orderby_options",
        "woocommerce_catalog_orderby",
        "woocommerce_pagination_args",
        "woocommerce_show_page_title",
        "woocommerce_order_button_text",
        "woocommerce_order_button_html",
        # Page-level brand surfaces migrated out of the now-deleted
        # `playground/wo-pages-mu.php` and `playground/wo-swatches-mu.php`
        # into per-theme `<theme>/functions.php` blocks between
        # `// === BEGIN <slug> ===` sentinels. Re-registering any of these
        # from `playground/` would silently double-paint in the demo and
        # disappear entirely on a real install.
        "woocommerce_before_customer_login_form",
        "woocommerce_after_customer_login_form",
        "woocommerce_cart_is_empty",
        "woocommerce_no_products_found",
        "woocommerce_before_main_content",
        "woocommerce_dropdown_variation_attribute_options_html",
        # `body_class` once carried the `theme-<slug>` filter from the
        # now-deleted `playground/wo-pages-mu.php`. Each theme now
        # hardcodes its own slug in the `// === BEGIN body-class ===`
        # block; playground has no business touching frontend body
        # classes.
        "body_class",
    }
    forbidden_prefix = (
        "render_block_woocommerce/",
        "woocommerce_blocks_",
    )

    # Marker classes that only ever appear inside theme-shipped paint
    # callbacks or theme-shipped patterns. If they reappear in any
    # `playground/*.php` file the brand surface is leaking out of the
    # theme directory: at runtime via a mu-plugin, or at seed time via
    # an inline HEREDOC inside `wo-configure.php` (the previous home of
    # the branded empty-cart-block before it migrated to each theme's
    # `patterns/cart-page.php`, which `wo-configure.php` now reads via
    # `include` + output buffering). Comments are stripped from the
    # source by the scrubber below so HISTORICAL NOTE blocks in the
    # gutted mu-plugins are safe.
    forbidden_markers = (
        "wo-empty",
        "wo-account-",
        "wo-archive-hero",
        "wo-swatch",
        "wo-payment-icons",
    )

    register_re = re.compile(
        r"add_(?:filter|action)\s*\(\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    )

    failures: list[str] = []
    files_scanned = 0
    for php_path in sorted(pg_dir.glob("*.php")):
        files_scanned += 1
        src = php_path.read_text(encoding="utf-8")
        # Strip line + block comments so a docstring example like
        # `add_filter('gettext', ...)` doesn't trip the gate.
        scrubbed = re.sub(r"//[^\n]*", "", src)
        scrubbed = re.sub(r"/\*[\s\S]*?\*/", "", scrubbed)
        for match in register_re.finditer(scrubbed):
            hook = match.group(1)
            denied = hook in forbidden_exact or any(hook.startswith(p) for p in forbidden_prefix)
            if not denied:
                continue
            # Allowlist: if the call sits inside a `defined('WO_*')`
            # guard within 200 chars upstream, treat as opt-out.
            window = scrubbed[max(0, match.start() - 200) : match.start()]
            if re.search(r"defined\s*\(\s*['\"]WO_[A-Z0-9_]+['\"]\s*\)", window):
                continue
            line_no = scrubbed.count("\n", 0, match.start()) + 1
            failures.append(
                f"  playground/{php_path.name}:{line_no}: registers "
                f"`{hook}` — that hook rewrites a string or HTML a "
                f"shopper reads on a real install. Move the filter into "
                f"`<theme>/functions.php` between the "
                f"`// === BEGIN wc microcopy ===` sentinels (or guard "
                f"the registration with `if ( defined( 'WO_DEMO_ONLY' ) )` "
                f"if it really is demo-only)."
            )

        # Marker scan: every `playground/*.php` source. Mu-plugins paint
        # at runtime; `wo-configure.php` paints via post_content seed —
        # both leak shopper-facing brand outside the theme directory if
        # they hardcode a `wo-*` marker. `wo-configure.php` previously
        # HEREDOC'd the branded empty-cart-block; that markup now comes
        # from `<theme>/patterns/cart-page.php` via `include` + output
        # buffering, so the marker stays scoped to the theme directory
        # and the gate can scan the seed script too.
        for marker in forbidden_markers:
            idx = scrubbed.find(marker)
            if idx == -1:
                continue
            line_no = scrubbed.count("\n", 0, idx) + 1
            failures.append(
                f"  playground/{php_path.name}:{line_no}: contains "
                f"`{marker}` marker — that class is part of a per-theme "
                f"paint callback or pattern (see `<theme>/functions.php` "
                f"`// === BEGIN <slug> ===` sentinels and "
                f"`<theme>/patterns/cart-page.php`). Painting it from "
                f"`playground/` would shadow the theme in the demo and "
                f"vanish on a real install."
            )

    if failures:
        r.fail(
            "playground/*.php registers brand-affecting filters; the "
            "release theme will paint with WC default strings because "
            "the mu-plugin doesn't ship with it. See AGENTS.md root-rule "
            '"Shopper-facing brand lives in the theme, not in '
            'playground/":\n' + "\n".join(failures)
        )
    else:
        r.details.append(
            f"scanned {files_scanned} playground/*.php file(s); no "
            f"brand-affecting filter registrations"
        )
    return r


def check_theme_ships_cart_page_pattern() -> Result:
    """Forbid a theme from missing `patterns/cart-page.php`.

    The Cart page's `post_content` is seeded by `playground/wo-configure.php`
    § 11d via `include` + output buffering of the active theme's
    `<theme>/patterns/cart-page.php`. Reading the pattern means the
    branded `wp:woocommerce/empty-cart-block` (with `wo-empty` /
    `wo-empty__title` / `wo-empty__lede` classes + per-theme microcopy
    + per-theme CTA labels) lives inside the theme directory and ships
    with it on a real install — a Proprietor who picks the Cart pattern
    from the editor's Cart-block placeholder dropdown gets exactly the
    same chrome as the Playground demo. Root rule: "Shopper-facing
    brand lives in the theme, not in playground/".

    The check enforces three guarantees per theme:

      1. The file `<theme>/patterns/cart-page.php` exists. Without it,
         the seed step in wo-configure.php silently leaves the Cart
         page on its default WC empty-cart text and the demo regresses
         to a generic "Your cart is currently empty!" line.

      2. The pattern header carries `Block Types: woocommerce/cart`,
         which is what surfaces the pattern in the editor's Cart-block
         placeholder picker on a real install (a Proprietor inserts
         the WC Cart block on a fresh page and the pattern dropdown
         offers this pre-built version). Without the header the file
         is invisible to the editor and a real install never gets the
         branded chrome even if wo-configure has run.

      3. The pattern body contains the branded `wo-empty` markers
         (eyebrow + title + lede + CTA buttons). Without them the
         pattern would seed an unstyled WC empty-cart-block and the
         per-theme empty-cart paint never reaches the shopper.
    """
    r = Result("Each theme ships patterns/cart-page.php with woocommerce/cart Block Types")
    pattern_path = ROOT / "patterns" / "cart-page.php"
    if not pattern_path.is_file():
        r.fail(
            "patterns/cart-page.php missing — `wo-configure.php` § 11d "
            "reads this file via `include` + `ob_start` to seed the "
            "Cart page `post_content`. Without the file the demo Cart "
            "regresses to WC's default empty-cart text and a real "
            "install never gets the branded chrome via the Cart-block "
            "placeholder picker."
        )
        return r

    src = pattern_path.read_text(encoding="utf-8")

    # 1. Block Types header.
    if not re.search(r"^\s*\*\s*Block Types:\s*woocommerce/cart\s*$", src, re.MULTILINE):
        r.fail(
            "patterns/cart-page.php: header is missing "
            "`Block Types: woocommerce/cart`. Without that line the "
            "pattern is invisible to the editor's Cart-block placeholder "
            "picker, so a Proprietor on a real install never sees this "
            "pattern offered when they insert a WC Cart block."
        )

    # 2. Branded empty-cart markers.
    required_markers = (
        "wo-empty wo-empty--cart",
        "wo-empty__eyebrow",
        "wo-empty__title",
        "wo-empty__lede",
    )
    missing = [m for m in required_markers if m not in src]
    if missing:
        r.fail(
            "patterns/cart-page.php: missing branded empty-cart "
            f"markers {missing}. The pattern's empty-cart-block must "
            "carry the same `wo-empty` / `wo-empty__eyebrow` / "
            "`wo-empty__title` / `wo-empty__lede` classes the theme's "
            "`// === BEGIN empty-states ===` callback uses, so the "
            "seeded Cart page picks up the per-theme empty-cart CSS."
        )

    # 3. Sanity: the cart root block must be present at all.
    if "<!-- wp:woocommerce/cart" not in src:
        r.fail(
            "patterns/cart-page.php: contains no `wp:woocommerce/cart` "
            "block — the file is in the right place but doesn't render "
            "a Cart block, so wo-configure.php would seed garbage into "
            "post_content."
        )

    if r.passed and not r.skipped:
        r.details.append(
            "cart-page.php present with `Block Types: woocommerce/cart` "
            "and the four `wo-empty*` markers"
        )
    return r


def check_wc_microcopy_distinct_across_themes() -> Result:
    """Fail if two themes' wc microcopy maps translate the same WC
    default string to the same override (excluding genuine universals
    on the allowlist).

    SAME-VOICE-EVERYWHERE FAIL MODE
    -------------------------------
    Each theme's `<theme>/functions.php` has a `// === BEGIN wc
    microcopy ===` block whose `static $map = array(...);` rewrites
    WC default strings into that theme's voice. A clone (`bin/clone.py`)
    copies obel verbatim, so a fresh variant ships with obel's voice
    until somebody rewrites the map. Without this gate, a side-by-side
    review of five themes reads as "one shop in different paint jobs"
    on every cart, checkout, account-login, and shop-archive surface
    — the exact failure mode the per-theme microcopy refactor exists
    to prevent.

    The check parses each theme's `static $map = array( 'WC default'
    => 'Theme override', ... );` block, groups translations by WC
    default key, and fails on any key whose translation repeats across
    two or more themes UNLESS the WC default is in the universal
    allowlist at `bin/wc_microcopy_universal.json`. The allowlist
    covers tiny utility verbs, single-word financial labels, and
    case-variant duplicates ("Username or email address" / "Username
    or Email Address") where forcing 5 distinct translations would
    feel artificial.

    Failure message names the WC default key, the duplicate translation,
    and the themes sharing it; the fix is to rewrite the offending
    theme's value in its own voice (preferred) or, very rarely, add
    the WC default to `bin/wc_microcopy_universal.json` with a
    one-line rationale.

    See AGENTS.md hard rule "Per-theme WC microcopy must be distinct
    across themes".
    """
    r = Result("WC microcopy maps are distinct across themes")
    allowlist_path = MONOREPO_ROOT / "bin" / "wc_microcopy_universal.json"
    allowlist: set[str] = set()
    if allowlist_path.is_file():
        try:
            raw = json.loads(allowlist_path.read_text(encoding="utf-8"))
            allowlist = {k for k in raw if not k.startswith("_comment")}
        except json.JSONDecodeError as exc:
            r.fail(f"wc_microcopy_universal.json: invalid JSON ({exc}).")
            return r

    begin = "// === BEGIN wc microcopy ==="
    end = "// === END wc microcopy ==="
    # PHP map entry: `'key' => 'value',` (single quotes only — the
    # render template ships single-quoted PHP literals).
    pair_re = re.compile(
        r"'((?:[^'\\]|\\.)*)'\s*=>\s*'((?:[^'\\]|\\.)*)'",
    )

    def php_unquote(literal: str) -> str:
        # PHP single-quoted strings: only \\ and \' are escaped.
        return literal.replace("\\'", "'").replace("\\\\", "\\")

    # theme_slug -> { wc_default -> override }
    per_theme: dict[str, dict[str, str]] = {}
    for theme_dir in iter_themes():
        fn_path = theme_dir / "functions.php"
        if not fn_path.is_file():
            continue
        src = fn_path.read_text(encoding="utf-8")
        if begin not in src or end not in src:
            # check_no_default_wc_strings flags the missing block
            # already; don't double-fail here, just skip the theme
            # in the cross-theme comparison.
            continue
        block = src[src.index(begin) : src.index(end) + len(end)]
        # Narrow to the first `static $map = array(...)` so we don't
        # accidentally pick up sort-label entries or other arrays.
        map_match = re.search(
            r"static\s+\$map\s*=\s*array\s*\(([\s\S]*?)\)\s*;",
            block,
        )
        if not map_match:
            continue
        map_body = map_match.group(1)
        per_theme[theme_dir.name] = {
            php_unquote(k): php_unquote(v) for k, v in pair_re.findall(map_body)
        }

    if len(per_theme) < 2:
        r.skip(
            f"only {len(per_theme)} theme(s) ship a wc microcopy map; "
            f"cross-theme comparison needs at least 2"
        )
        return r

    # All keys present in any theme. For each key we'll collect the
    # per-theme translations and look for duplicates.
    all_keys: set[str] = set()
    for m in per_theme.values():
        all_keys.update(m.keys())

    failures: list[str] = []
    pairs_checked = 0
    for key in sorted(all_keys):
        if key in allowlist:
            continue
        # value -> [theme slugs that translate to that value]
        by_value: dict[str, list[str]] = {}
        for slug, m in per_theme.items():
            if key in m:
                by_value.setdefault(m[key], []).append(slug)
        for value, slugs in by_value.items():
            pairs_checked += 1
            if len(slugs) >= 2:
                failures.append(
                    f"  {sorted(slugs)} all translate `{key}` -> "
                    f"`{value}`. Rewrite at least one in its own voice "
                    f"(or, if the WC default genuinely should not vary, "
                    f"add it to bin/wc_microcopy_universal.json)."
                )

    if failures:
        r.fail(
            f"WC microcopy maps share translations across themes "
            f"(checked {pairs_checked} per-key translations across "
            f"{len(per_theme)} themes; see the allowlist at "
            f"bin/wc_microcopy_universal.json for genuine universals):\n" + "\n".join(failures)
        )
    else:
        r.details.append(
            f"checked {pairs_checked} per-key translations across "
            f"{len(per_theme)} themes; every non-allowlisted "
            f"translation is unique"
        )
    return r


def check_playground_content_seeded() -> Result:
    """Fail if a theme ships a playground/blueprint.json without the
    matching playground/content/ + playground/images/ payload.

    UNSEEDED-PLAYGROUND FAIL MODE
    -----------------------------
    Every theme's `playground/blueprint.json` references its own
    `https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<theme>/playground/content/content.xml`
    (WXR import) and `.../content/products.csv` (WC seed step), and a
    fleet of `.../images/*` URLs the WXR + the WC seeder both reach for
    when sideloading attachments. If those files don't exist in the repo
    (or the seeded image set is missing) the live demo cascades:

        * raw.githubusercontent.com returns 404 for content.xml
        * the WXR import step bails
        * every subsequent `wp eval-file` (wo-import.php, wo-configure.php,
          wo-cart.php, …) crashes because it tries to read products WC
          never imported
        * the user sees an unbroken stream of `PHP.run() failed with
          exit code 1` in the browser console and a blank page

    The fix is `python3 bin/seed-playground-content.py --theme <slug>`
    followed by `python3 bin/sync-playground.py`, but the fail mode is
    invisible from a local checkout (the theme dir looks "complete" — it
    has a blueprint, templates, theme.json, patterns…). This check is
    the static gate that makes shipping an unseeded theme impossible.

    See AGENTS.md hard rule "Every Playground blueprint must ship its
    content payload alongside it".
    """
    r = Result("Playground blueprint has its content/ + images/ payload seeded")
    bp_path = ROOT / "playground" / "blueprint.json"
    if not bp_path.exists():
        r.skip("no playground/blueprint.json (theme without a Playground demo)")
        return r

    content_dir = ROOT / "playground" / "content"
    images_dir = ROOT / "playground" / "images"
    content_xml = content_dir / "content.xml"
    products_csv = content_dir / "products.csv"

    missing: list[str] = []
    if not content_xml.exists():
        missing.append("playground/content/content.xml")
    if not products_csv.exists():
        missing.append("playground/content/products.csv")
    if not images_dir.is_dir() or not any(images_dir.iterdir()):
        missing.append("playground/images/ (empty or missing)")

    if missing:
        r.fail(
            "this theme ships a playground/blueprint.json but is "
            "missing its content payload: "
            + ", ".join(missing)
            + ". The live demo will 404 on raw.githubusercontent.com "
            "and every PHP step in the blueprint will exit 1. Run "
            "`python3 bin/seed-playground-content.py --theme "
            f"{ROOT.name}` to copy the canonical wonders-oddities "
            "CSV/WXR/images into this theme, then "
            "`python3 bin/sync-playground.py` to refresh the inlined "
            "mu-plugins, then commit content/ + images/ + the updated "
            "blueprint together."
        )
        return r

    # Bonus: warn if the blueprint references image URLs whose files
    # don't exist on disk. The CSV/XML rewriter in the seed script
    # normally keeps these in sync, but a manual edit could drift.
    try:
        bp_text = bp_path.read_text(encoding="utf-8")
    except OSError:
        bp_text = ""
    image_url_re = re.compile(
        r"raw\.githubusercontent\.com/RegionallyFamous/fifty/main/"
        + re.escape(ROOT.name)
        + r"/playground/images/([A-Za-z0-9._-]+)"
    )
    referenced = set(image_url_re.findall(bp_text))
    on_disk = {p.name for p in images_dir.iterdir() if p.is_file()}
    drift = sorted(referenced - on_disk)
    if drift:
        # Cap the noise — show the first 5 missing files.
        head = ", ".join(drift[:5])
        more = f" (+{len(drift) - 5} more)" if len(drift) > 5 else ""
        r.fail(
            f"playground/blueprint.json references {len(drift)} image "
            f"file(s) that don't exist in playground/images/: {head}{more}. "
            "The blueprint will 404 on those URLs at boot. Re-run "
            "`python3 bin/seed-playground-content.py --theme "
            f"{ROOT.name}` to re-pull the missing assets."
        )
        return r

    asset_count = len(on_disk)
    r.details.append(f"content.xml + products.csv present; {asset_count} image asset(s) on disk")
    return r


def check_no_placeholder_product_images() -> Result:
    """Fail if a theme's `playground/content/products.csv` (or content.xml)
    references the upstream `wonders-<product-slug>.png` flat-cartoon
    placeholders instead of bespoke per-theme `product-wo-<slug>.jpg`
    photographs.

    PLACEHOLDER-IMAGERY FAIL MODE
    -----------------------------
    `bin/seed-playground-content.py` pulls the canonical
    `RegionallyFamous/wonders-oddities` catalogue, which ships flat
    illustrated cartoons under `wonders-<slug>.png` (mug silhouette on
    a yellow background, etc.). Those cartoons are never the look any
    theme actually wants -- every theme is supposed to ship its own
    visual voice as `product-wo-<slug>.jpg` photographs (Y2K iridescent
    chrome for aero, sepia workshop for selvedge, etc.). The seeder
    runs an *upgrade pass* that, when bespoke photos are present in
    `<theme>/playground/images/`, rewrites every CSV/XML reference from
    `wonders-<slug>.png` to `product-wo-<slug>.jpg` and deletes the
    cartoon files.

    The fail modes this check guards:

      * **No bespoke photos generated yet (the aero shape).** The
        seeder copied the upstream cartoons in but no one has produced
        per-theme photographs. The catalogue paints the demo with flat
        cartoons that look nothing like the theme. Fix: generate
        `product-wo-<slug>.jpg` photos for every product slug in this
        theme's voice, drop them in `playground/images/`, then re-run
        the seeder so the upgrade pass swaps the refs.

      * **Photos exist but the seeder upgrade pass never ran (the
        lysholm shape).** The bespoke `product-wo-<slug>.jpg` files
        sit on disk but the CSV/XML still point at the upstream
        cartoons. Fix: re-run `bin/seed-playground-content.py
        --theme <slug>` (idempotent -- it rewrites the refs and cleans
        up the now-unused cartoon PNGs).

      * **CSV references a `product-wo-<slug>.jpg` that's missing on
        disk.** The blueprint will 404 on that URL at boot. Fix: make
        sure the photo is committed at the expected path.

    Page/post hero placeholders (`wonders-page-*.png`,
    `wonders-post-*.png`) are deliberately excluded -- they live on a
    separate generation track and don't have `product-wo-*`
    counterparts.
    """
    r = Result("Product imagery is bespoke (no upstream placeholder cartoons)")
    csv_path = ROOT / "playground" / "content" / "products.csv"
    xml_path = ROOT / "playground" / "content" / "content.xml"
    images_dir = ROOT / "playground" / "images"

    if not csv_path.exists():
        r.skip("no playground/content/products.csv (theme without a Playground demo)")
        return r

    placeholder_re = re.compile(r"wonders-([a-z0-9-]+)\.png")
    bespoke_re = re.compile(r"product-wo-([a-z0-9-]+)\.jpg")

    on_disk = (
        {p.name for p in images_dir.iterdir() if p.is_file()} if images_dir.is_dir() else set()
    )

    failures: list[str] = []
    placeholder_slugs: set[str] = set()
    bespoke_slugs: set[str] = set()

    for label, path in (("products.csv", csv_path), ("content.xml", xml_path)):
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in placeholder_re.finditer(text):
            slug = m.group(1)
            if slug.startswith(("page-", "post-")):
                continue
            placeholder_slugs.add(slug)
        for m in bespoke_re.finditer(text):
            slug = m.group(1)
            bespoke_slugs.add(slug)
            if f"product-wo-{slug}.jpg" not in on_disk:
                failures.append(
                    f"playground/content/{label} references "
                    f"`product-wo-{slug}.jpg` but the file is missing from "
                    f"playground/images/. The live demo will 404 on that URL "
                    f"at boot. Re-run `python3 bin/seed-playground-content.py "
                    f"--theme {ROOT.name}` to re-pull the missing asset, or "
                    f"regenerate it."
                )

    if placeholder_slugs:
        sample = sorted(placeholder_slugs)[:5]
        more = f" (+{len(placeholder_slugs) - 5} more)" if len(placeholder_slugs) > 5 else ""
        sample_list = ", ".join(f"`wonders-{s}.png`" for s in sample)
        missing_photos = sorted(
            s for s in placeholder_slugs if f"product-wo-{s}.jpg" not in on_disk
        )
        if missing_photos:
            failures.append(
                f"playground/content/ references {len(placeholder_slugs)} "
                f"upstream cartoon placeholder image(s): "
                f"{sample_list}{more}.\n"
                f"  Of those, {len(missing_photos)} have NO bespoke "
                f"`product-wo-<slug>.jpg` photograph on disk for this theme -- "
                f"the catalogue will paint flat illustrated cartoons instead "
                f"of branded photography. Generate the missing photos as "
                f"`{ROOT.name}/playground/images/product-wo-<slug>.jpg` (one "
                f"per slug, in this theme's visual voice), then re-run "
                f"`python3 bin/seed-playground-content.py --theme {ROOT.name}` "
                f"to swap the CSV/XML refs and clean up the cartoons."
            )
        else:
            failures.append(
                f"playground/content/ references {len(placeholder_slugs)} "
                f"upstream cartoon placeholder image(s) "
                f"({sample_list}{more}) even though every "
                f"matching `product-wo-<slug>.jpg` photograph is already "
                f"on disk. The seeder's upgrade pass never ran on this "
                f"theme -- fix it by running `python3 "
                f"bin/seed-playground-content.py --theme {ROOT.name}` "
                f"(idempotent; rewrites the refs and deletes the now-unused "
                f"cartoons)."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if not bespoke_slugs:
        r.skip("no product image refs found in CSV/XML")
        return r

    r.details.append(
        f"{len(bespoke_slugs)} bespoke `product-wo-<slug>.jpg` ref(s); "
        f"no upstream placeholder cartoons remaining"
    )
    return r


def check_product_images_unique_across_themes() -> Result:
    """Fail if any `product-wo-<slug>.jpg` is byte-identical across two
    themes -- that's a copy-paste leak, not bespoke per-theme imagery.

    CROSS-THEME COPY-PASTE FAIL MODE
    --------------------------------
    Even when every theme ships the right *count* of
    `product-wo-<slug>.jpg` files (`check_no_placeholder_product_images`
    passes), an entire `playground/images/` folder can still have been
    cloned wholesale from another theme without per-theme regeneration.
    The catalogue then renders with the source theme's photography
    while everything else (`theme.json`, `style.css`, templates,
    patterns) tries to be a different brand. The two real-world hits:

      * **The aero shape (untracked-leftover):** during a generation
        pass, 7 product slugs were skipped, leaving `selvedge`'s
        scratch-copies in `aero/playground/images/`. Those 7 files
        were byte-identical to the matching `selvedge` photos. `git
        status` showed 30 added files and looked complete; only an
        md5/sha256 cross-check across themes surfaced the leak.

      * **The lysholm shape (theme-init copy-paste):** when `lysholm`
        was cloned from `obel` as a starting point, the entire
        `playground/images/` folder was copied verbatim. All 30
        `product-wo-<slug>.jpg` files were byte-identical to `obel`'s.
        The catalogue rendered with obel's quiet-editorial photography
        while the rest of the theme tried to be Nordic home-goods.

    The check sha256-hashes every theme's `playground/images/product-wo-*.jpg`
    files and fails when any two themes share the same digest. Page +
    post hero placeholders (`wonders-page-*.png`, `wonders-post-*.png`)
    live on a separate generation track and are intentionally excluded.

    Remediation hint: the check can't infer which theme is the copier
    vs. the original (no git context at check time), so it names both
    themes involved in the duplication and asks the human to regenerate
    the copier (typically the newer theme) using that theme's voice
    from `<theme>/style.css`'s Description.
    """
    import hashlib

    r = Result("Product photographs are unique across themes (no copy-paste leak)")

    by_hash: dict[str, list[str]] = {}
    total_photos = 0
    for theme in iter_themes():
        images_dir = theme / "playground" / "images"
        if not images_dir.is_dir():
            continue
        for path in sorted(images_dir.glob("product-wo-*.jpg")):
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            total_photos += 1
            by_hash.setdefault(digest, []).append(f"{theme.name}/{path.name}")

    if not total_photos:
        r.skip("no product-wo-*.jpg photographs found in any theme")
        return r

    leaks = [(h, files) for h, files in by_hash.items() if len(files) > 1]
    if leaks:
        themes_involved: dict[frozenset[str], list[tuple[str, list[str]]]] = {}
        for digest, files in leaks:
            theme_set = frozenset(f.split("/", 1)[0] for f in files)
            themes_involved.setdefault(theme_set, []).append((digest, files))

        for theme_set, group in sorted(themes_involved.items(), key=lambda kv: sorted(kv[0])):
            theme_list = ", ".join(sorted(theme_set))
            count = len(group)
            sample = sorted(files for _, files in group)[:3]
            sample_str = "; ".join(" == ".join(f) for f in sample)
            more = f" (+{count - 3} more)" if count > 3 else ""
            r.fail(
                f"{count} product-wo-*.jpg file(s) byte-identical across "
                f"[{theme_list}]: {sample_str}{more}. "
                f"At least one of these themes is shipping another "
                f"theme's photography under its own slug -- the live "
                f"demo will paint the wrong-theme aesthetic for those "
                f"products. Regenerate the duplicates in whichever "
                f"theme is the copier (typically the newer one) using "
                f"that theme's visual voice (see each theme's "
                f"`style.css` Description), drop the new files in "
                f"`<theme>/playground/images/`, and re-run this check "
                f"to confirm uniqueness."
            )
        return r

    r.details.append(
        f"{total_photos} `product-wo-*.jpg` file(s) hashed across all themes; "
        f"every photograph is byte-unique to its theme"
    )
    return r


def check_theme_screenshots_distinct() -> Result:
    """Fail when any two themes ship the same ``screenshot.png`` bytes.

    Background
    ----------
    Every WordPress theme has a ``screenshot.png`` (admin Themes screen
    card image, ~1200x900). The convention is that the screenshot is a
    representative shot of the theme rendering — for the Fifty monorepo
    that means the home page from the snap framework, cropped+resized
    by ``bin/build-theme-screenshots.py``.

    Before this check was added, every theme in the monorepo shipped
    the SAME placeholder bytes (md5 was identical across obel/chonk/
    lysholm/selvedge/aero), so the admin Themes grid showed five
    identical cards labelled with five different theme names. Catching
    that in CI keeps the regression from re-appearing — common ways it
    silently re-appears are:

        * `bin/clone.py` copying the source theme's screenshot.png
          verbatim into a new variant and the author forgetting to
          re-run the screenshot builder.
        * A theme being rebaselined but `bin/build-theme-screenshots.py`
          not being re-run, leaving an old screenshot pointing at a
          stale render.
        * A copy-paste between themes in a "fix everything in parallel"
          edit.

    What this check enforces
    ------------------------
    For every theme directory in the monorepo, hash its
    ``screenshot.png`` (sha-256, full file). If any two themes share a
    hash, fail with both theme names — that's the duplicate. Also fail
    if a theme is missing its screenshot.png entirely. We deliberately
    do NOT compare visual similarity — even cropping/resizing slight
    variations of the same source baseline produces distinct bytes, so
    a byte-exact match is the unambiguous regression signal.
    """
    import hashlib

    r = Result("Theme screenshots distinct (no duplicate-bytes)")

    by_hash: dict[str, list[str]] = {}
    for theme in iter_themes():
        path = theme / "screenshot.png"
        if not path.exists():
            r.fail(f"{theme.name}/: missing screenshot.png")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash.setdefault(digest, []).append(theme.name)

    for digest, themes in by_hash.items():
        if len(themes) > 1:
            r.fail(
                f"{', '.join(themes)} share identical screenshot.png "
                f"(sha256={digest[:12]}…). Re-run "
                f"`python3 bin/build-theme-screenshots.py` to regenerate "
                f"per-theme screenshots from each theme's home snap."
            )

    return r


# ---------------------------------------------------------------------------
# Heuristic-finding allowlist (READ-side mirror of `bin/snap.py`).
# ---------------------------------------------------------------------------
# The allowlist file at `tests/visual-baseline/heuristics-allowlist.json`
# is the single source of truth for "yes we know about this finding,
# don't fail the gate on it". `bin/snap.py` consults it at WRITE time
# (`_apply_allowlist_to_findings`) so the findings.json files it
# emits already have demotions baked in. But:
#
#   * On a fresh checkout the developer hasn't re-shot yet -- the
#     findings.json on disk was written before the allowlist landed.
#   * After `bin/snap.py allowlist regenerate` adds new entries, every
#     stale findings.json under tmp/ is now wrong by allowlist standards
#     until re-shot (~127s per theme).
#
# Either case has the static check failing on findings the allowlist
# already covers -- gate noise that pushes contributors back to
# `--no-verify`. Mirror the apply-at-read logic here so the source of
# truth wins regardless of when the findings.json was written. Kept
# small and self-contained on purpose -- the snap.py canonical version
# does the same thing with a cache + per-cell in-place mutation, but
# this read-only helper just needs (kind, fingerprint) -> bool.
#
# When updating: keep `_AXE_ALLOWLIST_PATH`, the key shape
# `theme:viewport:route`, and `_axe_finding_fingerprint`'s
# `fingerprint`-then-`selector` precedence in sync with
# `bin/snap.py:ALLOWLIST_PATH`, `_allowlist_key`, and
# `_finding_fingerprint`. There's a self-test in
# `tests/check_py/test_axe_allowlist.py` that asserts both
# implementations agree on a synthetic finding.
_AXE_ALLOWLIST_PATH = (
    MONOREPO_ROOT / "tests" / "visual-baseline" / "heuristics-allowlist.json"
)


def _load_axe_allowlist() -> dict[str, dict[str, set[str]]]:
    """Return `{theme:viewport:route -> {kind -> {fingerprint, ...}}}`.

    Missing/malformed file becomes `{}` (no suppressions). Sets
    instead of lists for O(1) membership tests in the hot loop below.
    """
    if not _AXE_ALLOWLIST_PATH.is_file():
        return {}
    try:
        data = json.loads(_AXE_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, set[str]]] = {}
    for key, kinds in data.items():
        if not isinstance(kinds, dict):
            continue
        cell: dict[str, set[str]] = {}
        for kind, fps in kinds.items():
            if not isinstance(fps, list):
                continue
            cell[str(kind)] = {str(fp) for fp in fps if isinstance(fp, str)}
        if cell:
            out[str(key)] = cell
    return out


def _axe_finding_fingerprint(f: dict) -> str | None:
    """Mirror of `bin/snap.py:_finding_fingerprint`. Prefer the
    explicit `fingerprint` field, fall back to `selector`. Returns
    None when neither is available -- matches snap.py's policy that
    such findings can't be allowlisted (they're an unconditional
    failure)."""
    fp = f.get("fingerprint")
    if isinstance(fp, str) and fp:
        return fp
    sel = f.get("selector")
    if isinstance(sel, str) and sel:
        return sel
    return None


def _axe_finding_is_allowlisted(
    allowlist: dict[str, dict[str, set[str]]],
    theme: str,
    viewport: str,
    route: str,
    finding: dict,
) -> bool:
    """True iff this finding's (kind, fingerprint) is registered for
    this (theme, viewport, route) cell. Findings already marked
    `allowlisted` (e.g. because snap.py demoted them at write time
    and a tool kept the marker) also count, so a stale findings.json
    that was generated against an older allowlist still respects
    today's policy."""
    if finding.get("allowlisted"):
        return True
    cell = allowlist.get(f"{theme}:{viewport}:{route}")
    if not cell:
        return False
    kind = str(finding.get("kind") or "")
    if kind not in cell:
        return False
    fp = _axe_finding_fingerprint(finding)
    if fp is None:
        return False
    return fp in cell[kind]


def check_no_serious_axe_in_recent_snaps() -> Result:
    """Fail if any `tmp/snaps/<theme>/<viewport>/*.findings.json` for the
    current theme records a `severity: "error"` finding (axe-core
    impact >= serious).

    Why this exists:
      `bin/snap.py` runs axe-core on every captured page and writes
      its violations into a per-route `*.findings.json` payload, with
      axe `serious`/`critical` mapped to our internal `error` severity
      (see `_AXE_IMPACT_TO_SEVERITY` in `bin/snap.py`). The visual
      gate (`bin/snap.py check`) already fails on those — but it's an
      OPT-IN step (`bin/check.py --visual`) that pre-commit and the
      default `--offline` CI loop don't invoke. The result is the
      embarrassing failure mode this check exists to prevent: a real
      axe-core violation (e.g. 1.27:1 placeholder contrast on
      Selvedge's checkout) sits in `tmp/snaps/.../findings.json` for
      hours, but the offline gate is green and pre-commit waves the
      change through.

      This check closes the loop without forcing every contributor to
      pay the 2-5 minute Playground boot cost in `--offline`: if the
      developer (or CI worker, or agent) HAS recently shot the theme,
      the artifacts on disk are treated as evidence and any serious
      finding fails the static gate. Re-shooting with the fix in
      place clears the artifacts; deleting them with `rm -rf
      tmp/snaps/<theme>` also clears the gate for contributors who
      haven't run snap at all.

    What this check enforces:
      Walk `tmp/snaps/<theme>/**/findings.json`. For each file, parse
      the top-level `findings: []` array and collect every entry
      where `severity == "error"`. Group by `kind` (e.g.
      `a11y-color-contrast`) so multiple repeated nodes of the same
      axe rule report as one group with a node count. Fail with the
      route+viewport coordinates so the offending page is one click
      away.

      Skips gracefully when:
        * `tmp/snaps/<theme>/` doesn't exist (developer never ran snap)
        * No `*.findings.json` exists under it (snap was interrupted)
        * Every findings file parses but contains no error-severity
          entries (theme is clean — the common path).
    """
    r = Result("Recent snaps carry no serious axe-core errors")
    snaps_dir = MONOREPO_ROOT / "tmp" / "snaps" / ROOT.name
    if not snaps_dir.is_dir():
        r.skip(f"no tmp/snaps/{ROOT.name}/ on disk (snap not run for this theme)")
        return r

    findings_files = sorted(snaps_dir.rglob("*.findings.json"))
    if not findings_files:
        r.skip(f"tmp/snaps/{ROOT.name}/ exists but has no *.findings.json files")
        return r

    allowlist = _load_axe_allowlist()
    failures: list[str] = []
    files_checked = 0
    error_total = 0
    allowlisted_total = 0
    for fp in findings_files:
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        findings = payload.get("findings") or []
        if not isinstance(findings, list):
            continue
        files_checked += 1
        # Derive (viewport, route) from the file path so we can ask the
        # allowlist whether each finding has already been triaged. Layout
        # is `tmp/snaps/<theme>/<viewport>/<route>.findings.json` (route
        # may itself contain dots, e.g. `checkout-filled.field-focus`).
        try:
            rel_to_snaps = fp.relative_to(snaps_dir)
            viewport = rel_to_snaps.parts[0]
            route = fp.stem
            if route.endswith(".findings"):
                route = route[: -len(".findings")]
        except (ValueError, IndexError):
            viewport, route = "", ""

        # Collapse same-kind errors so the message stays compact:
        # one entry per axe rule per route/viewport. Allowlisted
        # findings counted separately for the summary line so the
        # backlog stays visible without failing the gate.
        by_kind: dict[str, dict] = {}
        for f in findings:
            if not isinstance(f, dict):
                continue
            if f.get("severity") != "error":
                continue
            if _axe_finding_is_allowlisted(
                allowlist, ROOT.name, viewport, route, f
            ):
                allowlisted_total += 1
                continue
            kind = f.get("kind", "unknown")
            entry = by_kind.setdefault(kind, {"count": 0, "first": None, "axe_url": None})
            entry["count"] += 1
            if entry["first"] is None:
                entry["first"] = f.get("message", "")[:200]
                entry["axe_url"] = f.get("axe_help_url")
        if by_kind:
            try:
                rel = fp.relative_to(MONOREPO_ROOT)
            except ValueError:
                rel = fp
            for kind, info in sorted(by_kind.items()):
                error_total += info["count"]
                msg = f"  {rel}: {kind} x{info['count']} -- {info['first']}"
                if info["axe_url"]:
                    msg += f" (see {info['axe_url']})"
                failures.append(msg)

    if failures:
        hint = (
            f"{error_total} NEW severity:error finding(s) across snap "
            f"artifacts for {ROOT.name} (not in "
            f"tests/visual-baseline/heuristics-allowlist.json). Re-shoot "
            f"with the fix in place (`python3 bin/snap.py shoot "
            f"{ROOT.name}`) to clear, or `rm -rf tmp/snaps/{ROOT.name}` "
            f"if you intend to drop the evidence. If this is intentional "
            f"backlog, run `python3 bin/snap.py allowlist regenerate "
            f"--theme {ROOT.name}` to add the entries"
        )
        if allowlisted_total:
            hint += (
                f"; {allowlisted_total} pre-existing allowlisted "
                f"finding(s) suppressed"
            )
        r.fail(hint + ":\n" + "\n".join(failures))
        return r

    detail = (
        f"scanned {files_checked} findings file(s) under "
        f"tmp/snaps/{ROOT.name}/; no NEW severity:error entries"
    )
    if allowlisted_total:
        detail += (
            f" ({allowlisted_total} suppressed via "
            f"tests/visual-baseline/heuristics-allowlist.json)"
        )
    r.details.append(detail)
    return r


def check_evidence_freshness() -> Result:
    """Fail if uncommitted source edits are newer than the most recent
    snap evidence for this theme.

    Why this exists:
      AGENTS.md rule #18 says "snap before declaring done." Phase 1 of
      the closed-loop plan turns that aspiration into a gate. After
      you edit a theme.json/template/part/pattern/style/functions
      file, the corresponding `tmp/snaps/<theme>/**/findings.json`
      mtime should be newer than the source mtime -- otherwise the
      evidence is stale and the offline gate is reading findings
      from the PRE-edit world. Pre-commit then waves the change
      through because old findings happen to be green.

    What this enforces:
      For the current theme:
        1. Find every theme source file (theme.json, functions.php,
           templates/**, parts/**, patterns/**, styles/**) that has
           uncommitted edits in the working tree.
        2. Find the most recent `*.findings.json` mtime under
           `tmp/snaps/<theme>/`.
        3. Fail if any uncommitted source edit is newer than that
           findings mtime, OR if there's a source edit but no
           findings exist at all.

    Skips gracefully when:
      * `git` isn't available (no way to know what's uncommitted)
      * No uncommitted edits to source (committed code path -- the
        Phase 1 spec says we trust commits-with-snaps; freshness only
        gates the WIP path)
      * The escape hatch FIFTY_SKIP_EVIDENCE_FRESHNESS=1 is set (used
        by the pre-push hook AFTER it's already run a fresh visual
        gate; double-gating would be redundant).
    """
    r = Result("Snap evidence is fresh vs uncommitted source edits")
    if os.environ.get("FIFTY_SKIP_EVIDENCE_FRESHNESS") == "1":
        r.skip("FIFTY_SKIP_EVIDENCE_FRESHNESS=1 (pre-push already ran the visual gate)")
        return r
    if not shutil.which("git"):
        r.skip("git not available on PATH")
        return r

    theme_root = ROOT
    try:
        rel_theme = theme_root.relative_to(MONOREPO_ROOT)
    except ValueError:
        r.skip("theme outside monorepo root")
        return r

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", str(rel_theme)],
            cwd=str(MONOREPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        r.skip(f"git status failed: {e}")
        return r
    if proc.returncode != 0:
        r.skip(f"git status returned {proc.returncode}: {proc.stderr.strip()}")
        return r

    source_suffixes = {".json", ".php", ".html", ".css"}
    source_dirs = ("theme.json", "functions.php", "styles", "templates", "parts", "patterns", "playground")
    edited_sources: list[Path] = []
    for line in proc.stdout.splitlines():
        if not line or len(line) < 4:
            continue
        # Porcelain format: XY<space>path[ -> renamed-path]
        rest = line[3:]
        path_str = rest.split(" -> ")[-1].strip().strip('"')
        p = MONOREPO_ROOT / path_str
        if not p.is_file():
            continue
        try:
            sub = p.relative_to(theme_root)
        except ValueError:
            continue
        # Only count actual theme source files; tmp/, screenshot
        # regen, .DS_Store etc don't gate evidence freshness.
        first = sub.parts[0] if sub.parts else ""
        if first not in source_dirs and p.name not in {"theme.json", "functions.php"}:
            continue
        if p.suffix.lower() not in source_suffixes:
            continue
        edited_sources.append(p)

    if not edited_sources:
        r.skip("no uncommitted source edits in this theme")
        return r

    snaps_dir = MONOREPO_ROOT / "tmp" / "snaps" / theme_root.name
    findings_files = sorted(snaps_dir.rglob("*.findings.json")) if snaps_dir.is_dir() else []
    if not findings_files:
        r.fail(
            f"{len(edited_sources)} uncommitted source file(s) in {theme_root.name} "
            f"but no snap evidence exists at tmp/snaps/{theme_root.name}/. "
            f"Run `python3 bin/snap.py shoot {theme_root.name}` "
            "to generate fresh findings before committing."
        )
        return r

    latest_findings = max(f.stat().st_mtime for f in findings_files)

    stale: list[tuple[Path, float]] = []
    for src in edited_sources:
        try:
            src_mtime = src.stat().st_mtime
        except OSError:
            continue
        if src_mtime > latest_findings + 1.0:  # 1s slop for filesystem rounding
            stale.append((src, src_mtime - latest_findings))

    if stale:
        bullets = []
        for src, delta in sorted(stale, key=lambda x: -x[1])[:10]:
            try:
                rel = src.relative_to(MONOREPO_ROOT)
            except ValueError:
                rel = src
            bullets.append(f"  {rel} (newer than newest findings by {delta:.0f}s)")
        r.fail(
            f"{len(stale)} source file(s) edited after the latest snap "
            f"({len(findings_files)} findings file(s) under "
            f"tmp/snaps/{theme_root.name}/). Re-shoot with "
            f"`python3 bin/snap.py shoot {theme_root.name}` so findings "
            f"reflect the post-edit state, then re-run the gate.\n"
            + "\n".join(bullets)
        )
    return r


def check_wc_specificity_winnable() -> Result:
    """Fail if any selector in `bin/append-wc-overrides.py`'s CHUNKS
    has lower CSS specificity than the matching WooCommerce Blocks
    default selector.

    Why this exists:
      Today's Selvedge bug -- placeholder text rendering at 1.27:1
      against the input chrome -- was a cascade-loss: our override
      `body .wc-block-components-text-input input` (specificity
      0,1,2) was being beaten by WC Blocks' default
      `.wc-block-components-form .wc-block-components-text-input input`
      (0,3,1). Phase 1 of the closed-loop plan: detect this kind of
      cascade-loss STATICALLY, before the `body` prefix ever ships.

    How:
      1. Import bin/append-wc-overrides.py and walk every selector
         in its CSS chunks. Compute the selector's specificity.
      2. Group those selectors by their rightmost compound (base
         element + classes + attrs + pseudo-classes). For each
         compound, find the maximum specificity WC Blocks ships for
         the SAME compound (looked up in bin/wc-blocks-specificity.json).
      3. If our specificity is STRICTLY LESS THAN WC's max -> fail.
         Equal specificity is a win because theme styles load AFTER
         plugin styles (source-order tiebreaker).
      4. Filter out non-runtime WC selectors (editor-only, loading-
         state, theme-namespaced) so we don't chase ghosts.
      5. Honor bin/wc-specificity-known-losses.json: pre-existing
         losses are grandfathered so the gate only catches NEW
         regressions, not the historical tech debt this gate found
         on initial rollout. To regenerate the baseline after fixing
         losses, re-run this check and copy the reported losses
         into the JSON file (or delete the file to fail loud on
         everything).

    Skips when:
      * bin/wc-blocks-specificity.json is missing (run
        `python3 bin/build-wc-specificity-index.py`)
      * bin/append-wc-overrides.py is missing
    """
    r = Result("WC override selectors win the cascade vs WC Blocks defaults")
    spec_index = MONOREPO_ROOT / "bin" / "wc-blocks-specificity.json"
    overrides_script = MONOREPO_ROOT / "bin" / "append-wc-overrides.py"
    losses_baseline = MONOREPO_ROOT / "bin" / "wc-specificity-known-losses.json"
    if not spec_index.is_file():
        r.skip(
            f"missing {spec_index.relative_to(MONOREPO_ROOT)}; run "
            "`python3 bin/build-wc-specificity-index.py` to generate it"
        )
        return r
    if not overrides_script.is_file():
        r.skip(f"missing {overrides_script.relative_to(MONOREPO_ROOT)}")
        return r

    try:
        index = json.loads(spec_index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        r.fail(f"failed to read {spec_index}: {e}")
        return r

    wc_version = (index.get("_meta") or {}).get("wc_version", "unknown")
    wc_selectors: dict[str, tuple[int, int, int]] = {
        sel: tuple(spec) for sel, spec in (index.get("selectors") or {}).items()
    }

    grandfathered: set[str] = set()
    if losses_baseline.is_file():
        try:
            grandfathered = set(
                json.loads(losses_baseline.read_text(encoding="utf-8")).get("selectors") or []
            )
        except (OSError, json.JSONDecodeError):
            pass

    # Lazy-import the override script to get its CHUNKS list. The
    # script is sentinel-based so importing it doesn't run the
    # injection loop; the chunks are module-level constants.
    import importlib.util

    spec = importlib.util.spec_from_file_location("_append_wc_overrides", overrides_script)
    if spec is None or spec.loader is None:
        r.fail("failed to load bin/append-wc-overrides.py for selector inspection")
        return r
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as e:
        r.fail(f"failed to import bin/append-wc-overrides.py: {e}")
        return r

    chunks = getattr(module, "CHUNKS", None)
    if not chunks:
        r.skip("bin/append-wc-overrides.py has no CHUNKS attribute to inspect")
        return r

    sys.path.insert(0, str(MONOREPO_ROOT / "bin"))
    try:
        from build_wc_specificity_index import (  # type: ignore
            compute_specificity,
            iter_selectors,
        )
    except ImportError:
        # build-wc-specificity-index.py uses a hyphenated name; load
        # it directly via importlib instead.
        builder_path = MONOREPO_ROOT / "bin" / "build-wc-specificity-index.py"
        if not builder_path.is_file():
            r.skip("bin/build-wc-specificity-index.py not present; cannot parse selectors")
            return r
        builder_spec = importlib.util.spec_from_file_location(
            "_wc_spec_builder", builder_path
        )
        if builder_spec is None or builder_spec.loader is None:
            r.fail("failed to load build-wc-specificity-index.py")
            return r
        builder_mod = importlib.util.module_from_spec(builder_spec)
        try:
            builder_spec.loader.exec_module(builder_mod)  # type: ignore[union-attr]
        except Exception as e:
            r.fail(f"failed to import build-wc-specificity-index.py: {e}")
            return r
        compute_specificity = builder_mod.compute_specificity  # type: ignore[assignment]
        iter_selectors = builder_mod.iter_selectors  # type: ignore[assignment]

    # Index WC selectors by their rightmost compound so we can compare
    # apples to apples. WC's `.wc-block-components-form .text-input
    # input` compound key is `(input, set(), set(), set())`; our
    # `body .text-input input` compound key matches it.
    def _compound_key(selector: str) -> tuple[str, frozenset, frozenset, frozenset]:
        rightmost = re.split(r"\s*[ >+~]\s*", selector.strip())[-1]
        rightmost = re.sub(r"::[A-Za-z][A-Za-z0-9-]*", "", rightmost)
        type_match = re.match(r"^([a-zA-Z][a-zA-Z0-9-]*)", rightmost)
        base = type_match.group(1).lower() if type_match else ""
        classes = frozenset(re.findall(r"\.[A-Za-z_][A-Za-z0-9_-]*", rightmost))
        attrs = frozenset(re.findall(r"\[[^\]]+\]", rightmost))
        pcs = frozenset(
            m.group(0).split("(", 1)[0]
            for m in re.finditer(r":(?!:)[A-Za-z][A-Za-z0-9-]*(?:\([^)]*\))?", rightmost)
        )
        return (base, classes, attrs, pcs)

    # Filter out WC selectors that only fire in non-runtime contexts
    # (editor previews, loading shimmers, theme-specific has-* state
    # classes). Those legitimately have higher specificity but won't
    # paint over our overrides at visitor-render time.
    _NONRUNTIME_TOKENS = (
        ".editor-styles-wrapper",
        ".block-editor-",
        ".is-loading",
        ".is-disabled",
        ".has-dark-controls",
        ".has-light-controls",
        ".wp-admin",
    )

    def _wc_selector_is_runtime(sel: str) -> bool:
        return all(tok not in sel for tok in _NONRUNTIME_TOKENS)

    wc_by_compound: dict[tuple, tuple[tuple[int, int, int], str]] = {}
    for sel, spec_tuple in wc_selectors.items():
        if not _wc_selector_is_runtime(sel):
            continue
        key = _compound_key(sel)
        existing = wc_by_compound.get(key)
        if existing is None or spec_tuple > existing[0]:
            wc_by_compound[key] = (spec_tuple, sel)

    losses: list[str] = []
    selectors_checked = 0
    theme_only = 0
    grand_tolerated = 0

    for chunk in chunks:
        # CHUNKS entries in bin/append-wc-overrides.py are 4-tuples
        # `(sentinel_open, sentinel_close, css, prev_marker)`. Be
        # defensive: also accept dict / dataclass shapes if the
        # script is refactored later.
        css_text = ""
        if isinstance(chunk, (tuple, list)) and len(chunk) >= 3:
            css_text = chunk[2]
        elif isinstance(chunk, dict):
            css_text = chunk.get("css", "") or ""
        else:
            css_text = getattr(chunk, "css", "") or ""
        if not css_text:
            continue
        for sel in iter_selectors(css_text):
            selectors_checked += 1
            our_spec = compute_specificity(sel)
            key = _compound_key(sel)
            wc_entry = wc_by_compound.get(key)
            if wc_entry is None:
                theme_only += 1
                continue
            wc_spec, wc_sel = wc_entry
            if our_spec < wc_spec:
                if sel in grandfathered:
                    grand_tolerated += 1
                    continue
                losses.append(
                    f"  ours    = {our_spec}  ({sel})\n"
                    f"      WC max  = {wc_spec}  ({wc_sel})"
                )

    if losses:
        r.fail(
            f"{len(losses)} NEW override selector(s) lose the cascade "
            f"against WC Blocks (WC {wc_version}). Either boost specificity "
            f"in bin/append-wc-overrides.py (doubled-class trick: "
            f"`.foo.foo` instead of `body .foo`), or add the selector to "
            f"bin/wc-specificity-known-losses.json if you're knowingly "
            f"deferring the fix.\n" + "\n".join(losses)
        )
        return r

    r.details.append(
        f"{selectors_checked} override selector(s) checked vs WC "
        f"{wc_version}, {len(wc_selectors)} WC selectors indexed "
        f"({theme_only} theme-only selectors skipped); "
        f"{grand_tolerated} grandfathered loss(es) tolerated per "
        f"bin/wc-specificity-known-losses.json"
    )
    return r


def check_view_transitions_wired() -> Result:
    """Rule #22 — every theme MUST wire the four pieces of the cross-
    document View Transitions contract documented in AGENTS.md
    "View Transitions (cross-document)":

      1. CSS prelude in `theme.json` declares the opt-in plus a
         default `view-transition-type` (so `:root:active-view-
         transition-type(fifty-default)` selectors have something to
         match on the cold-path navigation).
      2. `render_block` filter in `functions.php` covers the four
         block names that render product/post titles and images
         (core/post-title, core/post-featured-image,
         woocommerce/product-image, woocommerce/product-image-gallery).
      3. The per-request dedup tracker is reset on `init` (otherwise
         long-lived PHP workers leak `view-transition-name` state
         between requests and silently drop names on later pages).
      4. The inline `pageswap`/`pagereveal` handler is registered on
         `wp_head` priority 1 (parser-blocking, classic script) AND
         the `<script type="speculationrules">` block is emitted from
         `wp_head`. Both must be present — the first makes the per-
         route flavor selectable from CSS, the second is the largest
         perceived-perf lever for cross-document VT.

    Failure mode this catches: a theme regressing on any of the four
    pieces (e.g. a clone that shipped before the WC product-image
    block was added to the filter) silently breaks the morph at
    runtime — `bin/snap.py`'s click-through probe will eventually
    catch it too, but this static gate fails the pre-push hook with
    a precise diagnostic instead of a manifest entry buried in tmp/.
    """
    r = Result("rule #22 — view transitions wired (theme.json + functions.php)")
    theme_json = ROOT / "theme.json"
    functions_php = ROOT / "functions.php"
    if not theme_json.exists():
        r.skip("no theme.json (not a theme directory)")
        return r
    if not functions_php.exists():
        r.fail("missing functions.php (theme cannot wire VT without it)")
        return r

    css = theme_json.read_text(encoding="utf-8")
    php = functions_php.read_text(encoding="utf-8")

    # Piece 1 — CSS prelude with @view-transition + at least one
    # named type that pairs with the JS handler in piece 4.
    if "@view-transition" not in css:
        r.fail(
            "theme.json styles.css is missing `@view-transition` opt-in "
            "(no cross-document transitions will fire)"
        )
    if "fifty-default" not in css:
        r.fail(
            "theme.json styles.css is missing the `types: fifty-default` "
            "descriptor on `@view-transition` — required so CSS rules can "
            "use `:root:active-view-transition-type(fifty-default)` for "
            "the cold-path navigation"
        )

    # Piece 2 — render_block filter MUST cover the four block names.
    # We grep for the literal block strings rather than parsing PHP
    # so a theme that registers an additional block name (e.g. a
    # custom card block) still passes — we only require the four
    # core+Woo blocks to be present.
    required_blocks = (
        "core/post-title",
        "core/post-featured-image",
        "woocommerce/product-image",
        "woocommerce/product-image-gallery",
    )
    missing_blocks = [b for b in required_blocks if b not in php]
    if missing_blocks:
        r.fail(
            "functions.php render_block filter does not name "
            + ", ".join(f"`{b}`" for b in missing_blocks)
            + " — cross-document image morph will silently no-op for "
            + "those block(s); extend the `$names` map in the "
            + "`render_block` filter"
        )

    # Piece 3 — per-request dedup reset on `init`.
    if "fifty_vt_assigned" not in php:
        r.fail(
            "functions.php is missing the `fifty_vt_assigned` per-page "
            "dedup tracker (long-lived PHP workers will leak "
            "`view-transition-name` state across requests)"
        )

    # Piece 4 — pageswap/pagereveal handler + speculationrules.
    if "fifty_view_transitions_inline_script" not in php:
        r.fail(
            "functions.php is missing the inline pageswap/pagereveal "
            "handler (`fifty_view_transitions_inline_script`) — without "
            "it the per-route flavor classes (fifty-shop-to-detail, "
            "fifty-paginate, fifty-cart-flow) never get added and the "
            "CSS in theme.json has nothing to match against"
        )
    elif "wp_head" not in php or "fifty_view_transitions_inline_script" not in php:
        r.fail(
            "the inline VT handler must be registered on `wp_head` so "
            "the pagereveal listener installs before the destination's "
            "first paint"
        )
    if "speculationrules" not in php:
        r.fail(
            "functions.php is missing the `<script type=\"speculationrules\">` "
            "block (`fifty_view_transitions_speculation_rules`) — the "
            "largest perceived-perf lever for cross-document VT"
        )

    if r.passed and not r.skipped:
        r.details.append(
            "@view-transition opt-in, types descriptor, 4 named blocks, "
            "dedup reset, inline pageswap handler, speculation rules — all wired"
        )
    return r


def check_no_unpushed_commits() -> Result:
    """Fail if local HEAD has commits that haven't reached origin yet.

    This catches a recurring silent-failure mode: an agent makes a fix,
    commits it, claims "fix is live", but never runs `git push`. The
    Playground demos load themes from `raw.githubusercontent.com/.../main/`
    so any commit that hasn't been pushed is invisible to anyone visiting
    the live demo, even though the local checkout, `git log`, and
    `bin/snap.py` (which mounts the local theme dir) all see the fix.

    We treat unpushed commits as a HARD FAIL rather than a warning so the
    CI/pre-commit loop refuses to declare success while a fix is sitting
    only on the local branch. The user can override by pushing or by
    rebasing the unpushed commits away.

    Skips gracefully if:
      * `git` isn't available
      * the working tree isn't a git repo
      * the current branch has no upstream (e.g. detached HEAD, or a
        feature branch that hasn't been published yet)

    The check is monorepo-wide -- it runs once per theme but always reports
    the same answer for the same git state. We don't dedupe because the
    extra ~10ms per theme is negligible and keeps the per-theme report
    self-contained.
    """
    r = Result("No unpushed commits on current branch (push before claiming a fix is live)")
    # Pre-push hook escape hatch: when this script is invoked FROM the
    # `.githooks/pre-push` hook, the to-be-pushed commits are by
    # definition not yet on the remote (that's the whole point of the
    # hook), so this check would deadlock the push it's supposed to
    # protect. The hook sets FIFTY_SKIP_UNPUSHED_CHECK=1 around its
    # `bin/check.py` invocation so this single check skips itself
    # while every other check still runs. Any other caller (CI, local
    # `bin/check.py`, pre-commit) leaves the env var unset and gets
    # the full check.
    if os.environ.get("FIFTY_SKIP_UNPUSHED_CHECK") == "1":
        r.skip(
            "FIFTY_SKIP_UNPUSHED_CHECK=1 (set by .githooks/pre-commit + pre-push to avoid in-flight-commit deadlock)"
        )
        return r
    if not shutil.which("git"):
        r.skip("git not available on PATH")
        return r
    try:
        # Use the monorepo root; the per-theme ROOT is a subdirectory so
        # `git -C` would also work, but MONOREPO_ROOT is the canonical anchor.
        cwd = str(MONOREPO_ROOT)
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            r.skip("not inside a git working tree")
            return r

        upstream = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if upstream.returncode != 0:
            r.skip("current branch has no upstream tracking ref")
            return r

        ahead = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if ahead.returncode != 0:
            r.skip(f"git rev-list failed: {ahead.stderr.strip()}")
            return r

        n = int(ahead.stdout.strip() or "0")
        if n > 0:
            unpushed = subprocess.run(
                ["git", "log", "--oneline", "@{u}..HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            r.fail(
                f"{n} unpushed commit{'s' if n != 1 else ''} on "
                f"{upstream.stdout.strip()}: run `git push` so the live "
                f"Playground demo (which loads theme/ from raw.githubusercontent.com) "
                f"actually sees them."
            )
            for line in unpushed.stdout.strip().splitlines():
                r.fail(f"  {line}")
    except (subprocess.TimeoutExpired, ValueError) as exc:
        r.skip(f"git probe failed: {exc}")
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
        check_block_markup_anti_patterns(),
        check_blocks_validator(),
        check_no_fake_forms(),
        check_no_empty_cover_blocks(),
        check_no_duplicate_templates(),
        check_no_duplicate_stock_indicator(),
        check_archive_sort_dropdown_styled(),
        check_no_squeezed_wc_sidebars(),
        check_wc_card_surfaces_padded(),
        check_wc_totals_blocks_padded(),
        check_wc_notices_styled(),
        check_navigation_overlay_opaque(),
        check_outline_button_paired_with_primary(),
        check_wc_card_padding_not_zeroed(),
        check_hover_state_legibility(),
        check_distinctive_chrome(),
        check_cart_checkout_pages_are_wide(),
        check_blueprint_landing_page(),
        check_front_page_unique_layout(),
        check_pdp_has_image(),
        check_pattern_microcopy_distinct(),
        check_all_rendered_text_distinct_across_themes(),
        check_no_default_wc_strings(),
        check_no_brand_filters_in_playground(),
        check_theme_ships_cart_page_pattern(),
        check_wc_microcopy_distinct_across_themes(),
        check_playground_content_seeded(),
        check_no_placeholder_product_images(),
        check_product_images_unique_across_themes(),
        check_theme_screenshots_distinct(),
        check_wc_specificity_winnable(),
        check_no_serious_axe_in_recent_snaps(),
        check_evidence_freshness(),
        check_view_transitions_wired(),
        check_no_unpushed_commits(),
    ]

    for r in results:
        print(r.render())

    failed = [r for r in results if not r.passed and not r.skipped]
    skipped = [r for r in results if r.skipped]

    print()
    if failed:
        print(
            f"{RED}FAILED{RESET}: {len(failed)} of {len(results)} checks failed for {theme_root.name}."
        )
        return 1
    if skipped:
        print(
            f"{GREEN}OK{RESET}: all checks passed for {theme_root.name} ({len(skipped)} skipped)."
        )
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
    parser.add_argument(
        "--visual",
        action="store_true",
        help=(
            "After all static checks pass, also run the visual-snapshot "
            "framework (`bin/snap.py check`) which boots Playground for "
            "the affected themes, captures Playwright screenshots across "
            "snap_config.ROUTES x VIEWPORTS, diffs against the "
            "committed baselines under `tests/visual-baseline/`, and "
            "applies the tiered heuristic gate (`bin/snap.py report "
            "--strict`). Default scope is `--visual-scope=changed` "
            "(only re-shoots themes touched by git diff); pass "
            "`--visual-scope=all` for the full sweep before a release."
        ),
    )
    parser.add_argument(
        "--visual-scope",
        choices=["changed", "all", "quick"],
        default="changed",
        help=(
            "How wide a visual sweep to run when --visual is passed. "
            "'changed' (default) -> only themes touched by uncommitted "
            "+ <visual-base>..HEAD git diff (framework changes fall back "
            "to all). 'all' -> every theme, every route, every viewport "
            "(2-5 min). 'quick' -> the snap_config.QUICK_* subset for a "
            "single theme; falls back to obel if no theme is selected."
        ),
    )
    parser.add_argument(
        "--visual-base",
        default=None,
        help=(
            "Git base ref for --visual-scope=changed (e.g. main, HEAD~1). "
            "Default: only consider uncommitted changes."
        ),
    )
    parser.add_argument(
        "--visual-threshold",
        type=float,
        default=0.5,
        help=(
            "Max %% changed pixels per (route, viewport) cell before the "
            "visual diff fails. Default 0.5%% (~one button-sized region). "
            "Only used when --visual is passed."
        ),
    )
    args = parser.parse_args()

    offline = args.offline or args.quick

    if args.all:
        exit_codes = []
        for theme in iter_themes():
            print(f"\n{'=' * 60}")
            exit_codes.append(run_checks_for(theme, offline))
        static_rc = 1 if any(exit_codes) else 0
    else:
        theme_root = resolve_theme_root(args.theme)
        static_rc = run_checks_for(theme_root, offline)

    # Visual diff runs LAST and only if static checks already passed.
    # Bailing out early on a static failure avoids spending 2-5 minutes
    # booting Playgrounds for code that won't compile.
    if static_rc != 0 or not args.visual:
        return static_rc

    # Late-import so contributors who never run --visual don't pay for
    # importing Playwright/Pillow on every check.
    print(f"\n{'=' * 60}")
    snap_path = str(Path(__file__).resolve().parent / "snap.py")
    if args.visual_scope == "quick":
        # `quick` shoots the snap_config.QUICK_* subset for one theme
        # (default obel) -- the absolute fastest way to verify a CSS
        # tweak didn't blow up the inner loop. Falls through to a
        # plain `shoot --quick` (no diff/report); use `--visual-scope
        # =changed` for the gated path.
        target_theme = args.theme if not args.all else "obel"
        print(f"Running quick visual smoke (`bin/snap.py shoot {target_theme} --quick`)...\n")
        snap_cmd = [sys.executable, snap_path, "shoot", target_theme, "--quick"]
    else:
        print(
            f"Running visual snapshot diff (`bin/snap.py check --scope={args.visual_scope}`)...\n"
        )
        snap_cmd = [
            sys.executable,
            snap_path,
            "check",
            f"--threshold={args.visual_threshold}",
        ]
        if args.visual_scope == "changed":
            snap_cmd.append("--changed")
            if args.visual_base:
                snap_cmd.extend(["--changed-base", args.visual_base])
    snap_rc = subprocess.call(snap_cmd, cwd=str(Path(__file__).resolve().parent.parent))
    return snap_rc


if __name__ == "__main__":
    sys.exit(main())
