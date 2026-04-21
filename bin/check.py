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
            out = out[:i] + out[j + len(close_marker):]
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
            out = out[:i] + out[j + len(close_marker):]
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
            scanned = (
                _strip_allowed_hex_chunks(node)
                if path.endswith("styles.css")
                else node
            )
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
                    f"{rel}:{lineno}: hardcoded contentSize \"{m.group(1)}\". "
                    f"Drop the override (uses settings.layout.contentSize), or use "
                    f"\"var(--wp--style--global--wide-size)\" / \"var(--wp--custom--layout--<slug>)\"."
                )
            for m in aspect_ratio_re.finditer(line):
                r.fail(
                    f"{rel}:{lineno}: hardcoded aspectRatio \"{m.group(1)}\". "
                    f"Use \"var(--wp--custom--aspect-ratio--<slug>)\"."
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
    """
    r = Result("Block markup matches save() output (group classes, button shadow, paragraph classes)")

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
        r'<!--\s*wp:paragraph\s+(\{[^>]*?\})\s*-->\s*\n\s*(<p\s+[^>]*>)',
        re.MULTILINE,
    )

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
            if 'has-border-color' in tag:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/group declares border.color but rendered <{tag.split()[0][1:]}> "
                f"is missing the `has-border-color` class. Add it to the class list."
            )

        # Invariant 2: paragraph legacy wo-empty__ class
        for m in para_block_re.finditer(text):
            tag = m.group(2)
            if 'wo-empty__' in tag:
                lineno = text.count("\n", 0, m.start(2)) + 1
                r.fail(
                    f"{rel}:{lineno}: core/paragraph carries a legacy `wo-empty__*` class. "
                    f"Remove it -- core/paragraph doesn't preserve unknown classes through save()."
                )

        # Invariant 3: button shadow on outer wrapper
        for m in button_outer_shadow_re.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/button has `box-shadow` on the outer "
                f"`.wp-block-button` div. Move it to the inner `a.wp-block-button__link` -- "
                f"that's where save() places it."
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
    headers = [
        line.strip() for line in proc.stderr.splitlines() if line.startswith("─── ")
    ]
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

    palette_list = (
        ((data.get("settings") or {}).get("color") or {}).get("palette") or []
    )
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
    color_re = re.compile(
        r"(?:^|[;{\s])color\s*:\s*var\(--wp--preset--color--([a-z0-9-]+)\)"
    )
    bg_re = re.compile(
        r"\bbackground(?:-color)?\s*:\s*var\(--wp--preset--color--([a-z0-9-]+)\)"
    )
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

    r.details.append(
        f"{checked} hover/focus state rule(s) verified at ≥3:1 contrast"
    )
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
                if sel == surface or sel.startswith(surface + " ") or sel.endswith(" " + surface) or sel.startswith(surface + ":") or sel.startswith(surface + "."):
                    if sel != surface:
                        # Only the *bare* selector (no descendant /
                        # state suffix) describes the panel itself; a
                        # descendant rule like `.wc-block-cart__sidebar
                        # .wp-block-heading` is internal type, not the
                        # panel.
                        continue
                    has_bg = re.search(
                        r"\bbackground(?:-color)?\s*:\s*(?!transparent\b|none\b|inherit\b|initial\b|unset\b)[^;}]+",
                        body,
                    ) is not None
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

    r.details.append(
        f"{len(bg_surfaces)} painted card surface(s) — all use "
        f"≥xl internal padding"
    )
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
    r = Result(
        "WC totals blocks (cart + checkout) have ≥xl internal padding"
    )

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
        f"{len(TOTALS_SELECTORS)} totals block(s) — all carry ≥xl "
        f"internal padding (Phase H)"
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
    r = Result(
        "WC painted card surfaces don't get horizontal padding zeroed"
    )

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
            s
            for s in sel_list
            if any(f".{cls}" in s for cls in _CARD_SURFACE_CLASSES)
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
            rest = sel_norm[len(prefix):]
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
                slug for slug in slugs
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

    Fix is in `playground/wo-configure.php`: both root blocks carry
    `{"align":"wide"}` so they opt out of the prose contentSize and
    use the theme's wideSize (1280px) instead. At 1280px the
    1fr / minmax(300px,360px) grid breathes correctly: ~880px form,
    ~360px sidebar.

    This rule asserts the marker is present in the `wo-configure.php`
    that ships in `theme.json`-adjacent code paths -- specifically the
    inlined copy in each theme's `playground/blueprint.json` (which is
    what the live demos actually run).
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

    # Find the inlined wo-configure.php content. sync-playground.py emits
    # it as a `writeFile` step at `wp-content/mu-plugins/wo-configure.php`.
    target_data: str | None = None
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
            target_data = data
            break

    if target_data is None:
        # No inlined wo-configure.php means the blueprint either uses a
        # different content-seeding strategy or hasn't been synced. Either
        # way this rule cannot validate the cart/checkout block markup.
        r.skip("no inlined wo-configure.php in blueprint (run bin/sync-playground.py)")
        return r

    required = [
        ('wp:woocommerce/cart {"align":"wide"}',
         "Cart root block (`wp:woocommerce/cart`) is missing "
         "`{\"align\":\"wide\"}`. Without it the cart inherits "
         "`contentSize:prose` (~560px) from `templates/page.html` and "
         "the sidebar collapses on desktop, producing per-letter text "
         "wrapping in the totals column."),
        ('wp:woocommerce/checkout {"align":"wide"}',
         "Checkout root block (`wp:woocommerce/checkout`) is missing "
         "`{\"align\":\"wide\"}`. Without it the checkout inherits "
         "`contentSize:prose` (~560px) from `templates/page.html` and "
         "the order-summary sidebar collapses on desktop, producing "
         "per-letter wraps of product names like 'Artisanal Silence'."),
    ]
    for needle, message in required:
        if needle not in target_data:
            r.fail(message)

    # Belt and suspenders: the rendered wrapper div must also carry
    # `alignwide` so the front-end CSS picks up the wide-width rules.
    # WordPress derives the class from the block attribute, but our
    # heredoc writes the wrapper div by hand; if the editor ever
    # re-saves the page the class will be regenerated correctly, but
    # the seeded source must already match so first paint is correct.
    div_required = [
        ('wp-block-woocommerce-cart alignwide',
         "Cart wrapper div is missing the `alignwide` class. The wrapper "
         "must read `<div class=\"wp-block-woocommerce-cart alignwide is-loading\">` "
         "to match the `align:wide` block attribute on first render."),
        ('wp-block-woocommerce-checkout alignwide',
         "Checkout wrapper div is missing the `alignwide` class. The wrapper "
         "must read `<div class=\"wp-block-woocommerce-checkout alignwide wc-block-checkout is-loading\">` "
         "to match the `align:wide` block attribute on first render."),
    ]
    for needle, message in div_required:
        if needle not in target_data:
            r.fail(message)

    if r.passed and not r.skipped:
        r.details.append(
            "verified `align:wide` on cart + checkout root blocks AND "
            "matching `alignwide` class on wrapper divs in inlined "
            "wo-configure.php"
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
                f"image are the loudest \"this site is broken\" tell on "
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
SHARED_HEADING_ALLOWLIST = frozenset({
    "shop", "categories", "cart", "checkout", "account", "my account",
    "log in", "register", "search results", "404", "page not found",
    "shop by category", "featured products", "new arrivals", "on sale",
    "related products", "you may also like", "your cart", "order summary",
    "billing", "shipping", "payment", "order details",
})


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
                    f"\"{short}\" — rewrite in {theme_slug}'s voice"
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
                        f"{rel}: ships heading \"{h}\" shared verbatim "
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
                            f"{rel}: heading \"{h}\" shares the phrase "
                            f"\"{shared}\" with {other_slug}'s heading "
                            f"\"{o}\" — pick a phrase no other theme is "
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
    r'<!--\s*wp:(?:heading|paragraph|button|list-item|verse|pullquote|preformatted)\s+'
    r'(\{[^}]*?"content"\s*:\s*"((?:\\.|[^"\\])*)"[^}]*?\})\s*/?-->',
    re.DOTALL,
)

ALL_TEXT_INNER_HTML_RE = re.compile(
    r'<(?:h[1-6]|p|li|figcaption|blockquote|button|a)[^>]*>([^<]{4,})'
    r'</(?:h[1-6]|p|li|figcaption|blockquote|button|a)>'
)

ALL_TEXT_PHP_TX_RE = re.compile(
    r"""(?<![A-Za-z0-9_])(?:esc_html_e|esc_html__|esc_attr_e|esc_attr__|_e|__)\s*\(\s*"""
    r"""(['"])((?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)

# Generic wayfinding / system text every store needs end-to-end. Each
# entry must already be normalised (lowercased, whitespace collapsed,
# trailing punctuation stripped) — see `_normalize_for_text_audit`.
ALL_TEXT_ALLOWLIST = frozenset({
    # short imperatives + nav (most are <12 chars and won't reach the
    # check anyway, but we list them defensively)
    "shop", "cart", "checkout", "account", "my account", "log in",
    "login", "register", "search", "menu", "home", "about", "contact",
    "blog", "journal", "read more", "view all", "view cart",
    "add to cart", "shop all", "shop now", "learn more", "all", "next",
    "previous", "back", "close", "open", "submit", "subscribe",
    "newsletter", "instagram", "twitter", "facebook", "pinterest",
    "tiktok", "returns", "shipping", "help", "faq", "support", "press",
    "careers", "company", "product", "products", "collection",
    "collections", "categories", "category",
    # 404 / search empty states
    "page not found", "search results", "no results", "no posts",
    # cart / checkout system labels
    "continue shopping", "order summary", "subtotal", "total", "tax",
    "discount", "view details", "see details", "read the journal",
    "read the story",
    # short attribute / image labels often shared by design (alt-text,
    # status pills, etc.)
    "in stock", "out of stock", "free", "sold out", "on sale",
})


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
                f"{other_slug}/{other_rel} — \"{shown}\" — rewrite in "
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
            while (
                i + k < len(a)
                and j + k < len(b)
                and a[i + k] == b[j + k]
            ):
                k += 1
            if k > 0:
                phrase = " ".join(a[i : i + k])
                if len(phrase) > len(best):
                    best = phrase
    return best


def check_no_default_wc_strings() -> Result:
    """Fail if the wo-microcopy-mu.php inlined into blueprint.json doesn't
    suppress every default-WC string the demo critique calls out.

    DEFAULT-WC-STRING FAIL MODE
    ---------------------------
    Even after Phases A–E reskin every WC surface, three or four strings
    on the cart, account login, and shop archive are unmistakable
    "this is a stock WooCommerce install" tells:

        - "Showing 1-16 of 55 results"  (loop result count)
        - "Default sorting"             (catalog-sorting first option)
        - "Estimated total"             (cart totals label)
        - "Proceed to Checkout"         (order-button text)
        - "Lost your password?"         (account form link)

    We override them all in `playground/wo-microcopy-mu.php`, which is
    inlined verbatim into each theme's `playground/blueprint.json` by
    `bin/sync-playground.py`. If a future edit to the mu-plugin or the
    sync script ever drops one of those overrides, this check fires
    against the rendered blueprint so the regression is impossible to
    miss in CI.

    The check is per-theme because the per-theme constants
    (`WO_THEME_NAME`, `WO_THEME_SLUG`, `WO_CONTENT_BASE_URL`) are
    prepended to the inlined data; we want to confirm the mu-plugin
    survived that prepend in every theme's blueprint.

    See AGENTS.md hard rule "No default WC strings on the live demo".
    """
    r = Result("Default WC microcopy is overridden in inlined wo-microcopy-mu.php")
    bp_path = ROOT / "playground" / "blueprint.json"
    if not bp_path.exists():
        r.skip("no playground/blueprint.json (theme without a Playground blueprint)")
        return r
    try:
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"playground/blueprint.json: invalid JSON ({exc}).")
        return r

    target_data: str | None = None
    for step in bp.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        if step.get("step") != "writeFile":
            continue
        if "wo-microcopy-mu.php" not in (step.get("path") or ""):
            continue
        data = step.get("data")
        if isinstance(data, str):
            target_data = data
            break

    if target_data is None:
        r.fail(
            "playground/blueprint.json has no inlined "
            "wo-microcopy-mu.php writeFile step. The demo will paint "
            "with WC's default strings (\"Showing 1-16 of 55 results\", "
            "\"Default sorting\", \"Estimated total\", \"Proceed to "
            "Checkout\", \"Lost your password?\"). Run "
            "`python3 bin/sync-playground.py` to inline the mu-plugin."
        )
        return r

    # Each entry: a fragment of the override that MUST appear in the
    # inlined PHP, plus the user-facing default string it displaces.
    # Fragments are intentionally narrow (the WP filter callback body)
    # so a future refactor that splits the filter into multiple closures
    # still works as long as the displaced string still gets replaced.
    required = [
        ("woocommerce_blocks_cart_totals_label",
         "\"Estimated total\" cart totals label"),
        ("woocommerce_order_button_text",
         "\"Proceed to Checkout\" / \"Place order\" button text"),
        ("woocommerce_default_catalog_orderby_options",
         "\"Default sorting\" catalog-sorting first option"),
        ("Lost your password?",
         "\"Lost your password?\" account login link"),
        ("wo-result-count",
         "\"Showing 1-16 of 55 results\" loop result count"),
    ]
    for needle, label in required:
        if needle not in target_data:
            r.fail(
                f"inlined wo-microcopy-mu.php is missing the override "
                f"for {label} (looked for `{needle}`). The default "
                f"string will paint on the live demo."
            )

    if r.passed and not r.skipped:
        r.details.append(
            f"all {len(required)} default-WC microcopy overrides "
            f"present in inlined mu-plugin"
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
    r.details.append(
        f"content.xml + products.csv present; "
        f"{asset_count} image asset(s) on disk"
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
        r.skip("FIFTY_SKIP_UNPUSHED_CHECK=1 (set by .githooks/pre-commit + pre-push to avoid in-flight-commit deadlock)")
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
        check_no_duplicate_templates(),
        check_no_duplicate_stock_indicator(),
        check_archive_sort_dropdown_styled(),
        check_no_squeezed_wc_sidebars(),
        check_wc_card_surfaces_padded(),
        check_wc_totals_blocks_padded(),
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
        check_playground_content_seeded(),
        check_no_unpushed_commits(),
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
        print(f"Running quick visual smoke "
              f"(`bin/snap.py shoot {target_theme} --quick`)...\n")
        snap_cmd = [sys.executable, snap_path, "shoot", target_theme, "--quick"]
    else:
        print(f"Running visual snapshot diff "
              f"(`bin/snap.py check --scope={args.visual_scope}`)...\n")
        snap_cmd = [
            sys.executable, snap_path, "check",
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
