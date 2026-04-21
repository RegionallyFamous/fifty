#!/usr/bin/env python3
"""Visual-snapshot framework for the Fifty theme repo.

Boots each theme's WordPress Playground locally (via @wp-playground/cli),
captures Playwright screenshots across `bin/snap_config.py`'s routes ×
viewports, and optionally diffs against committed baselines so the agent
loop doesn't depend on a human shipping screenshots back over chat.

Why this exists
---------------

The agent that maintains these themes can't load
playground.wordpress.net (in-app browser detection refuses to run the
wasm runtime). It also can't ask the user for a screenshot every time it
adjusts a single padding token. This script closes that loop:

  1. Boot WP+WC+theme locally on http://localhost:9400 using the SAME
     blueprint that the live demo uses, but with the local theme dir
     mounted on top of the GitHub-installed copy so unsynced edits show
     up. ~30-60s first boot, ~10-15s on subsequent boots that hit the
     playground cache in ~/.npm/_npx.
  2. Drive a headless Chromium across every (route, viewport) defined
     in snap_config.py, full-page screenshots saved as PNGs.
  3. Optional: compare each PNG against a committed baseline in
     `tests/visual-baseline/` and fail if too many pixels changed.

How the agent uses it
---------------------

Common loops:

  # See what a single theme looks like at desktop right now (fast):
  python3 bin/snap.py shoot chonk --quick
  # -> reads tmp/snaps/chonk/desktop/*.png

  # Full visual sweep before a PR:
  python3 bin/snap.py shoot --all
  # -> ~10 routes × 4 viewports × 4 themes ≈ 160 PNGs

  # Did anything change vs baseline?
  python3 bin/snap.py diff --all
  # -> exit 1 if any (route, viewport) crosses the threshold

  # I changed something on purpose; re-baseline:
  python3 bin/snap.py baseline --all          # whole theme matrix
  python3 bin/snap.py baseline chonk checkout-filled desktop  # one cell

  # Leave a server running for interactive poking via the
  # cursor-ide-browser MCP:
  python3 bin/snap.py serve chonk
  # -> blocks; visit http://localhost:9400/ ; Ctrl-C to stop

Integration with bin/check.py
-----------------------------

`bin/check.py --visual` runs `shoot --all` + `diff --all` and exits 1 on
any regression above the threshold. It is OPT-IN because a full sweep
adds 2-5 minutes to the check cycle; the standard `--quick` checks stay
fast for the inner loop.

Layout of generated files
-------------------------

  tmp/snap-blueprint-<theme>.json   Mutated blueprint (installTheme step
                                    stripped, wo-configure version bumped
                                    if needed). Regenerated each shoot.
  tmp/snaps/<theme>/<vw>/<slug>.png Latest captures from `shoot`.
  tmp/diffs/<theme>/<vw>/<slug>.*   Per-pixel diff PNGs + diff_summary.json
                                    written by `diff`.
  tests/visual-baseline/...         Committed baselines (PNGs only).

`tmp/` is .gitignored. `tests/visual-baseline/` is committed.

Why NOT wp-env, wp-now, or a local LAMP stack
---------------------------------------------

  * wp-env requires Docker; agent-side install friction + slow boot.
  * wp-now is deprecated; the project moved to @wp-playground/cli.
  * Local LAMP wouldn't reuse the Playground blueprints that already
    encode our content seeding, plugin install, and config. Reusing the
    blueprint means "what the snap shows" exactly matches "what the
    live demo at demo.regionallyfamous.com shows", which is the whole
    point of having a demo.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Add `bin/` to sys.path so we can import snap_config when running this
# file from the repo root (the most common invocation).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from snap_config import (
    BUDGETS,
    INSPECT_SELECTORS,
    INTERACTIONS,
    KNOWN_NOISE_SUBSTRINGS,
    QUICK_ROUTES,
    QUICK_VIEWPORTS,
    ROUTES,
    THEME_ORDER,
    VIEWPORTS,
    Interaction,
    Route,
    Viewport,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / "tmp"
SNAPS_DIR = TMP_DIR / "snaps"
DIFFS_DIR = TMP_DIR / "diffs"
BLUEPRINTS_DIR = TMP_DIR / "snap-blueprints"
BASELINE_DIR = REPO_ROOT / "tests" / "visual-baseline"


# ---------------------------------------------------------------------------
# ANSI helpers (kept local to avoid pulling in colorama). bin/check.py uses
# the same convention.
# ---------------------------------------------------------------------------
def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


_C = _supports_color()
GREEN = "\033[32m" if _C else ""
RED = "\033[31m" if _C else ""
YELLOW = "\033[33m" if _C else ""
DIM = "\033[2m" if _C else ""
RESET = "\033[0m" if _C else ""


# ---------------------------------------------------------------------------
# Theme + blueprint discovery
# ---------------------------------------------------------------------------
def _changed_themes(base: str | None = None) -> list[str] | None:
    """Return the subset of themes affected by uncommitted + base..HEAD
    git changes.

    Returns:
      None             -> framework changed (bin/, snap_config.py); the
                          caller should fall back to "all themes".
      []               -> nothing relevant changed; nothing to shoot.
      ["obel", ...]    -> only those themes need a reshoot.

    Path mapping (theme dir IS the git root):
      <theme>/**                       -> theme is affected
      tests/visual-baseline/<theme>/** -> theme is affected
      bin/**, snap_config.py           -> framework; all themes
      anything else                    -> no theme affected
    """
    known = set(discover_themes())
    paths: set[str] = set()
    try:
        # Uncommitted (staged + unstaged + untracked tracked files).
        for cmd in (
            ["git", "diff", "--name-only", "HEAD"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                               text=True, check=False)
            if r.returncode == 0:
                paths.update(p for p in r.stdout.splitlines() if p)
        if base:
            r = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...HEAD"],
                cwd=REPO_ROOT, capture_output=True, text=True, check=False,
            )
            if r.returncode == 0:
                paths.update(p for p in r.stdout.splitlines() if p)
    except FileNotFoundError:
        # git not installed -- can't be smart, fall back to "all".
        return None

    if not paths:
        return []

    affected: set[str] = set()
    for p in paths:
        parts = p.split("/")
        head = parts[0]
        if head in known:
            affected.add(head)
            continue
        if head == "tests" and len(parts) >= 3 and parts[1] == "visual-baseline":
            if parts[2] in known:
                affected.add(parts[2])
            continue
        # Framework-level changes invalidate every theme's snaps.
        if head == "bin" or head in ("snap_config.py",):
            return None
    return sorted(affected)


def discover_themes() -> list[str]:
    """Return theme slugs (folder names) that have a theme.json + blueprint.

    Honours snap_config.THEME_ORDER for stable ordering; any new theme
    folder discovered on disk is appended after the configured order.
    """
    have = {
        p.parent.name
        for p in REPO_ROOT.glob("*/theme.json")
        if (p.parent / "playground" / "blueprint.json").exists()
    }
    ordered = [t for t in THEME_ORDER if t in have]
    extras = sorted(have - set(ordered))
    return ordered + extras


def theme_dir(theme: str) -> Path:
    return REPO_ROOT / theme


def blueprint_path(theme: str) -> Path:
    return theme_dir(theme) / "playground" / "blueprint.json"


# ---------------------------------------------------------------------------
# Blueprint mutation: produce a "snap blueprint" that uses local files.
# ---------------------------------------------------------------------------
def build_local_blueprint(theme: str, login: bool = False) -> Path:
    """Clone the theme's blueprint and strip the GitHub installTheme step.

    The original blueprint installs the theme from
        git:directory  https://github.com/RegionallyFamous/fifty  ref=main
    which is the right thing for the live demos but wrong for local
    iteration: it would pull whatever's on `main`, ignoring uncommitted
    edits. Our snap server starts with `--mount=<theme-dir>:/wordpress/
    wp-content/themes/<theme>` so the local files are present before
    activateTheme runs; all we need to remove is the installTheme step
    that would otherwise fail (target dir already populated by the mount)
    or, worse, succeed and overwrite our mount point.

    Anything else (plugin install, content seeding, wo-configure.php)
    stays identical to the live blueprint -- which is why the snap
    matches what users see at demo.regionallyfamous.com.

    `login=False` strips the blueprint's root-level `"login": true`. That
    field auto-issues an admin session via a runtime wp-cli login step,
    which (a) makes every screenshot include the 32px black admin bar
    along the top, ruining pixel-diff usefulness, (b) hides the real
    visible top of the theme, and (c) auto-fills checkout fields with
    admin@localhost.com so we lose the empty-form view real visitors
    see. `serve` overrides this and asks for login=True so the user can
    poke /wp-admin/.
    """
    src = blueprint_path(theme)
    if not src.exists():
        raise SystemExit(f"No blueprint at {src}")

    bp = json.loads(src.read_text(encoding="utf-8"))
    steps = bp.get("steps") or []

    # Strip installTheme; keep an `activateTheme` step in case one exists
    # separately, otherwise inject one because activation is what the
    # original installTheme step did via options.activate=true.
    new_steps = []
    had_install = False
    had_explicit_activate = False
    for step in steps:
        if not isinstance(step, dict):
            new_steps.append(step)
            continue
        if step.get("step") == "installTheme":
            had_install = True
            continue
        if step.get("step") == "activateTheme":
            had_explicit_activate = True
        new_steps.append(step)

    if had_install and not had_explicit_activate:
        # Insert activateTheme as the first step so the rest of the
        # blueprint (which assumes the theme is active, e.g. for
        # wo-configure.php's options) sees the right active stylesheet.
        new_steps.insert(
            0,
            {"step": "activateTheme", "themeFolderName": theme},
        )

    bp["steps"] = new_steps
    # `landingPage` may still be a deep link; for snap server we always
    # land on `/` so the boot probe in wait_for_server() succeeds quickly.
    bp["landingPage"] = "/"
    # See login docstring above; default to logged-out unless caller
    # explicitly opted in.
    if not login:
        bp.pop("login", None)
    else:
        bp["login"] = True

    BLUEPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    out = BLUEPRINTS_DIR / f"{theme}.json"
    out.write_text(json.dumps(bp, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
def find_free_port(preferred: int = 9400) -> int:
    """Return a free TCP port, preferring the requested one."""
    for candidate in [preferred, *range(9400, 9500)]:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            try:
                s.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    raise SystemExit("No free port in 9400-9499 for the playground server.")


@dataclass
class Server:
    proc: subprocess.Popen
    port: int
    log_path: Path
    log_handle: object  # file handle being kept open for line-buffered writes

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _probe(url: str, timeout_s: float = 3.0) -> tuple[int, str] | None:
    """HEAD-style probe that returns (status, location) without following
    redirects. Returns None on connection error.

    We can't use urlopen() because it auto-follows redirects and raises
    on the install.php <-> / loop that WP serves during the brief window
    between WordPress download and blueprint completion. Treating that
    loop as a fatal "boot failure" was the bug in v1; here it's just
    "server is alive but blueprint hasn't finished yet, keep waiting".
    """
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def http_error_301(self, *a, **kw): return None
        def http_error_302(self, *a, **kw): return None
        def http_error_303(self, *a, **kw): return None
        def http_error_307(self, *a, **kw): return None
        def http_error_308(self, *a, **kw): return None

    opener = urllib.request.build_opener(_NoRedirect())
    req = urllib.request.Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            return resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        # 4xx counts as "alive" -- the server processed our request,
        # blueprint just hasn't installed the route yet.
        return e.code, ""
    except (TimeoutError, urllib.error.URLError, ConnectionError):
        return None


# Sentinel string emitted by @wp-playground/cli's `server` command after
# (a) WordPress is installed, (b) the blueprint has finished executing
# every step, and (c) the server is accepting workers. Polling the
# server log for this is the most reliable "blueprint truly done" signal
# available -- HTTP probes only tell us that the server *accepts*
# requests (which happens earlier; WC may still be sideloading product
# images for another minute after the first 200 lands on /shop/).
#
# The CLI prints this after blueprint completion regardless of the
# blueprint's content, so it's a stable contract we can depend on
# without coupling to wo-configure.php internals. WP-CLI step output
# (like our wo-configure.php's `WP_CLI::success("W&O configure done.")`)
# does NOT make it to this stdout stream because it's captured by the
# wp-cli step runner inside the playground worker, not the cli host.
BLUEPRINT_DONE_MARKER = "Ready! WordPress is running on"


def wait_for_server(server: Server, timeout_s: float = 600.0) -> None:
    """Two-phase wait for the playground server to be ready for screenshots.

    Phase 1: server is alive at all (any HTTP response counts).
    Phase 2: BLUEPRINT_DONE_MARKER has appeared in the server log.

    First-boot timeout is intentionally generous (default 10 min) because
    the chain is: npx download (~10s, cached after first run) → WP
    download (~5s) → 2 plugin installs (~10s) → WXR import (~5s) →
    wo-import.php sideloads ~30 product images from raw.githubusercontent
    (~60-180s on flaky networks) → wo-configure.php sideloads ~6 category
    images (~30-60s) → permalink flush. Cached subsequent boots typically
    complete in ~30s when the playground engine reuses its WP filesystem
    cache, otherwise reset back to first-boot duration.
    """
    start = time.monotonic()
    phase = "alive"
    last_status: tuple[int, str] | None = None
    while time.monotonic() - start < timeout_s:
        if server.proc.poll() is not None:
            tail = server.log_path.read_text(errors="replace")[-2000:]
            raise SystemExit(
                f"Playground server died during boot (exit "
                f"{server.proc.returncode}). Last log output:\n{tail}"
            )

        if phase == "alive":
            r = _probe(server.url + "/?_snap_probe=1")
            if r is not None:
                phase = "ready"
                print(f"  {DIM}server alive after "
                      f"{time.monotonic()-start:.0f}s "
                      f"(status {r[0]}); waiting for "
                      f"`{BLUEPRINT_DONE_MARKER}` in log…{RESET}",
                      flush=True)
        else:  # phase == "ready"
            # Read the blueprint log; once `W&O configure done.` appears
            # we know every product image, category image, and cart/
            # checkout option has been written. Until then keep waiting.
            try:
                log_data = server.log_path.read_text(errors="replace")
            except FileNotFoundError:
                log_data = ""
            if BLUEPRINT_DONE_MARKER in log_data:
                print(f"  {DIM}blueprint complete after "
                      f"{time.monotonic()-start:.0f}s.{RESET}", flush=True)
                # Final settle: WC's option cache and permalink rewrites
                # take a beat to flush after the last WP_CLI::success.
                time.sleep(3.0)
                return
            # Sanity-probe /shop/ to detect early server death (the log
            # marker would never appear if the runtime crashed).
            last_status = _probe(server.url + "/shop/")
        time.sleep(2.0)

    raise SystemExit(
        f"Playground server at {server.url} did not finish blueprint "
        f"within {timeout_s:.0f}s (last /shop/ probe: {last_status}). "
        f"Tail of log:\n"
        f"{server.log_path.read_text(errors='replace')[-3000:]}"
    )


def boot_server(theme: str, port: int | None = None,
                verbosity: str = "normal", login: bool = False) -> Server:
    """Spawn `npx @wp-playground/cli@latest server` and return the handle.

    The caller is responsible for shutting it down via `kill_server()`
    in a finally block. Logs are streamed to tmp/<theme>-server.log so
    failures can be diagnosed even after the process exits.

    `login=False` by default because the snap workflow targets
    logged-out screenshots (what real visitors see). Logging in injects
    the 32px WP admin bar across the top of every shot, which (a) shifts
    every other element down so pixel diffs trip on every cell, and
    (b) hides the actual top of the theme template. `serve` and ad-hoc
    debugging pass `login=True` so the user can poke at /wp-admin/.
    """
    bp = build_local_blueprint(theme, login=login)
    chosen_port = port or find_free_port()
    mount_arg = f"{theme_dir(theme)}:/wordpress/wp-content/themes/{theme}"
    log_path = TMP_DIR / f"{theme}-server.log"
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "wb")

    cmd = [
        "npx",
        "--yes",
        "@wp-playground/cli@latest",
        "server",
        f"--port={chosen_port}",
        f"--blueprint={bp}",
        f"--mount={mount_arg}",
        f"--verbosity={verbosity}",
    ]
    if login:
        cmd.append("--login")
    print(
        f"{DIM}>{RESET} {' '.join(cmd)}\n"
        f"{DIM}  log:{RESET} {log_path}",
        flush=True,
    )
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=REPO_ROOT,
    )
    return Server(proc=proc, port=chosen_port, log_path=log_path, log_handle=log_handle)


def kill_server(server: Server) -> None:
    if server.proc.poll() is None:
        server.proc.terminate()
        try:
            server.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.proc.kill()
            server.proc.wait(timeout=5)
    try:
        server.log_handle.close()
    except Exception:
        pass


@contextlib.contextmanager
def running_server(theme: str, port: int | None = None,
                   verbosity: str = "normal", login: bool = False):
    """Context manager that boots, waits, and tears down."""
    server = boot_server(theme, port=port, verbosity=verbosity, login=login)
    try:
        wait_for_server(server)
        yield server
    finally:
        kill_server(server)


# ---------------------------------------------------------------------------
# Capture (Playwright)
# ---------------------------------------------------------------------------
def filter_routes(slugs: Iterable[str] | None) -> list[Route]:
    if not slugs:
        return list(ROUTES)
    wanted = set(slugs)
    return [r for r in ROUTES if r.slug in wanted]


def filter_viewports(names: Iterable[str] | None) -> list[Viewport]:
    if not names:
        return list(VIEWPORTS)
    wanted = set(names)
    return [v for v in VIEWPORTS if v.name in wanted]


_FREEZE_CSS = """
/* Injected by bin/snap.py before every screenshot to suppress
   pixel-diff noise from animations, cursor blinks, scrollbars, and
   web fonts that haven't fully swapped yet. We DON'T disable
   scrollbars globally because doing so changes layout width on
   platforms that reserve scrollbar gutter; we just hide the visible
   thumb so that scroll position differences don't trip diffs. */
*, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    scroll-behavior: auto !important;
    caret-color: transparent !important;
}
::-webkit-scrollbar-thumb { background: transparent !important; }
/* WC mini-cart drawer mounting flicker: force collapsed during shots. */
.wc-block-mini-cart__drawer:not(.is-mobile) { display: none !important; }
"""


# JS run via page.evaluate() after navigation. Returns a serialisable
# dict of findings + per-selector measurements. Kept side-effect free
# (no clicks, no DOM mutation) so it doesn't change what the screenshot
# captures.
_HEURISTICS_JS = r"""
(args) => {
    const out = {findings: [], selectors: []};
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const isMobile = vw < 600;
    out.dom = {width: vw, height: vh,
               scrollWidth: document.documentElement.scrollWidth,
               scrollHeight: document.documentElement.scrollHeight};

    const push = (sev, kind, msg, extra) => out.findings.push(
        Object.assign({severity: sev, kind, message: msg}, extra || {})
    );

    // Visibility helper used by several detectors. "Visible-ish" means
    // it has size, isn't hidden by display/visibility, and is in (or
    // near) the viewport vertically. The 4000px below-fold tolerance
    // catches images that lazy-load below the fold but ARE present.
    const isVisible = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return false;
        if (r.bottom < 0 || r.top > vh + 4000) return false;
        const cs = window.getComputedStyle(el);
        return cs.visibility !== 'hidden' && cs.display !== 'none'
            && cs.opacity !== '0';
    };

    // Horizontal page overflow -- the body is wider than the viewport.
    // Anything > 1px is treated as accidental (browsers report 0 or 1
    // even on perfectly fitting pages depending on rounding).
    const overflow = document.documentElement.scrollWidth - vw;
    if (overflow > 1) {
        push("warn", "horizontal-overflow",
             `Document scrollWidth ${document.documentElement.scrollWidth}px exceeds viewport ${vw}px by ${overflow}px.`,
             {overflow_px: overflow});
    }

    // Visible WooCommerce error / info / success notices. These
    // surface server-side problems that don't appear in the JS console
    // (e.g. "product is out of stock" when the cart preload fails).
    const noticeSelectors = [
        ['.woocommerce-error', 'error', 'wc-error'],
        ['.woocommerce-info', 'warn', 'wc-info'],
        ['.woocommerce-message', 'info', 'wc-message'],
        ['.wc-block-components-validation-error', 'warn', 'wc-validation-error'],
    ];
    for (const [sel, sev, kind] of noticeSelectors) {
        document.querySelectorAll(sel).forEach((el) => {
            const text = (el.innerText || '').trim().slice(0, 240);
            if (text) push(sev, kind, text, {selector: sel});
        });
    }

    // PHP/debug noise leaked into the page body.
    const debugRegex = /(Notice:\s|Warning:\s|Fatal error:|Parse error:|Deprecated:|Stack trace:|<br\s*\/>\s*<b>)/i;
    if (debugRegex.test(document.body.innerText || '')) {
        const m = (document.body.innerText.match(debugRegex) || [''])[0];
        push("error", "php-debug-output",
             `Page body contains PHP debug output (matched: ${m.trim()}).`);
    }

    // Untranslated/raw template tokens left in the rendered DOM.
    const rawToken = /__\(['"]/;
    if (rawToken.test(document.body.innerText || '')) {
        push("warn", "raw-i18n-token",
             "Page body contains a raw __() i18n token (string never translated).");
    }

    // Images: missing alt + broken + oversized + responsive mismatch +
    // SVG placeholder leakage (a real product image was expected but a
    // grey placeholder shipped instead, which is the silent class of
    // "demo looks empty" bug).
    document.querySelectorAll('img').forEach((img) => {
        const r = img.getBoundingClientRect();
        const visible = r.width > 0 && r.height > 0 && r.bottom >= 0 && r.top <= vh + 4000;
        if (!visible) return;
        const src = img.currentSrc || img.src || '';
        if (img.complete && img.naturalWidth === 0) {
            push("error", "broken-image",
                 `Image failed to load: ${src}`, {src});
            return;  // no further size checks for a broken image
        }
        if (!img.hasAttribute('alt')) {
            push("warn", "img-missing-alt",
                 `Image has no alt attribute: ${src}`, {src});
        }
        if (img.naturalWidth > 4000) {
            push("info", "img-oversized",
                 `Image is ${img.naturalWidth}px wide natively (consider a smaller variant).`,
                 {src, natural_width: img.naturalWidth});
        }
        // Responsive mismatch: pick obvious over-/under-served
        // variants. We use 2x as the over-serve ceiling (DPR=2 is the
        // common ceiling for retina display) and 0.6x as the
        // under-serve floor (anything noticeably soft on the chosen
        // viewport).
        const renderedW = Math.round(r.width);
        if (renderedW >= 32 && img.naturalWidth > 0) {
            if (img.naturalWidth > renderedW * 3) {
                push("info", "responsive-image-overserved",
                     `Served ${img.naturalWidth}px wide for a ${renderedW}px slot (>3x; wasted bytes).`,
                     {src, natural_width: img.naturalWidth, rendered_width: renderedW});
            } else if (img.naturalWidth > 0
                       && img.naturalWidth < renderedW * 0.75) {
                push("warn", "responsive-image-blurry",
                     `Served ${img.naturalWidth}px wide for a ${renderedW}px slot (<0.75x; will look soft).`,
                     {src, natural_width: img.naturalWidth, rendered_width: renderedW});
            }
        }
        // Placeholder-image: a grey/SVG placeholder ended up where a
        // real product image was expected. WC sometimes does this when
        // the post-thumbnail meta is missing.
        const looksPlaceholder = (
            src.startsWith('data:image/svg+xml')
            || /placeholder|woocommerce-placeholder/i.test(src)
        );
        // Inside any product-image surface (gallery, card, summary).
        const inProductSurface = !!img.closest(
            '.wp-block-post-featured-image, '
            + '.woocommerce-product-gallery, '
            + '.wc-block-components-product-image, '
            + '.wp-block-woocommerce-product-image, '
            + '.wc-block-grid__product-image'
        );
        if (looksPlaceholder && inProductSurface) {
            push("warn", "placeholder-image",
                 `Placeholder image rendered where a product image was expected: ${src.slice(0, 120)}`,
                 {src});
        }
    });

    // Per-character word-wrap detector: an element whose intrinsic
    // text width is much greater than its rendered width usually means
    // its container collapsed below the text's minimum content width.
    // We sample headings + button text inside known sidebar selectors
    // because that's where the WC sidebar squeeze manifested ("CAR T
    // TOT ALS" rendered as four lines of 1-3 chars each).
    const sidebarLike = [
        '.wc-block-cart__sidebar', '.wc-block-checkout__sidebar',
        '.wc-block-components-sidebar-layout__sidebar', 'aside',
    ];
    sidebarLike.forEach((side) => {
        document.querySelectorAll(`${side} h1, ${side} h2, ${side} h3, ${side} button, ${side} a.wc-block-cart__submit-button`).forEach((el) => {
            const r = el.getBoundingClientRect();
            const text = (el.innerText || '').trim();
            if (!text || r.width < 1) return;
            // Approximate the intrinsic word width: the longest word's
            // pixel width if rendered on a single line.
            const longestWord = text.split(/\s+/).reduce((a,b) => a.length >= b.length ? a : b, '');
            if (longestWord.length < 4) return;
            // Use a temporary inline span to measure unbroken text.
            const probe = document.createElement('span');
            probe.style.cssText = 'position:absolute;left:-99999px;top:-99999px;white-space:nowrap;font:inherit;letter-spacing:inherit;';
            probe.textContent = longestWord;
            el.appendChild(probe);
            const probeWidth = probe.getBoundingClientRect().width;
            el.removeChild(probe);
            if (probeWidth > r.width + 2) {
                push("warn", "word-broken",
                     `"${text.slice(0,80)}" appears to wrap mid-word inside ${side} (longest token ${longestWord} measures ${Math.round(probeWidth)}px but element is ${Math.round(r.width)}px).`,
                     {selector: side, element_width: Math.round(r.width), token_width: Math.round(probeWidth)});
            }
        });
    });

    // Web-font load state. If the document.fonts API hasn't reached
    // 'loaded' by the time we screenshot, the page snapped while a
    // FOUT was still in progress -- the captured PNG is unstable and
    // pixel diffs will trip on the next run when the font finally
    // swaps. Most theme work uses self-hosted fonts so this should
    // virtually always be 'loaded'; flag it when not.
    try {
        if (document.fonts && document.fonts.status
                && document.fonts.status !== 'loaded') {
            push("warn", "font-not-loaded",
                 `document.fonts.status is "${document.fonts.status}" at screenshot time (FOUT risk).`,
                 {status: document.fonts.status});
        }
    } catch (e) { /* fonts API not available -- skip */ }

    // Tap-target sizing. WCAG 2.5.5 calls for a 44x44 minimum hit
    // area; we use 32x32 as the practical floor (the bar most modern
    // theme.json typography passes naturally). Mobile-only because
    // mouse pointers don't have the same fat-finger problem.
    if (isMobile) {
        const tapEls = document.querySelectorAll(
            'a[href], button:not(:disabled), [role="button"], '
            + 'input[type="submit"], input[type="button"], '
            + 'input[type="reset"], summary'
        );
        tapEls.forEach((el) => {
            if (!isVisible(el)) return;
            const r = el.getBoundingClientRect();
            // Some links are inline runs of text (e.g. a footer link
            // inside a paragraph); the surrounding line gives the real
            // hit area. Skip elements whose text is wider than the
            // measured box (i.e. wrapped inline content).
            const cs = window.getComputedStyle(el);
            if (cs.display === 'inline' && r.width >= 32) return;
            if (r.width < 32 || r.height < 32) {
                const label = (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40);
                push("warn", "tap-target-too-small",
                     `Mobile tap target ${Math.round(r.width)}x${Math.round(r.height)}px (<32px) for "${label}".`,
                     {width: Math.round(r.width), height: Math.round(r.height), label});
            }
        });
    }

    // Text-overflow ellipsis that's actively truncating content. The
    // user is silently losing information; usually means the
    // surrounding container is too narrow.
    document.querySelectorAll('*').forEach((el) => {
        const cs = window.getComputedStyle(el);
        if (cs.textOverflow !== 'ellipsis') return;
        if (cs.overflow !== 'hidden') return;
        if (!isVisible(el)) return;
        if (el.scrollWidth > el.clientWidth + 1) {
            const txt = (el.innerText || '').trim().slice(0, 60);
            push("info", "text-overflow-truncated",
                 `Ellipsis is hiding content: "${txt}" (scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}).`,
                 {scroll_width: el.scrollWidth, client_width: el.clientWidth});
        }
    });

    // Empty landmarks. <main>, <nav>, <aside> with no visible text
    // usually mean a template fell through (block didn't render, query
    // returned 0 results) without anyone noticing.
    document.querySelectorAll('main, nav, aside').forEach((el) => {
        if (!isVisible(el)) return;
        // Some empty landmarks are deliberate (e.g. a <nav> whose only
        // visible content is icons) -- check for ANY visible text or
        // visible img inside before reporting.
        const text = (el.innerText || '').trim();
        const hasIcon = el.querySelector('img, svg, [role="img"]');
        if (text.length === 0 && !hasIcon) {
            push("info", "empty-landmark",
                 `<${el.tagName.toLowerCase()}> landmark has no visible text or media.`,
                 {tag: el.tagName.toLowerCase()});
        }
    });

    // Duplicate `view-transition-name` collisions. Chrome's view-
    // transitions API REQUIRES every active `view-transition-name`
    // value to be unique on the page; collisions throw
    // `InvalidStateError: Transition was aborted because of invalid
    // state` on the next navigation AND log "Unexpected duplicate
    // view-transition-name: <name>" to the console. The error is
    // invisible during a single static `page.goto` (transitions
    // only fire on navigation), so we have to detect it from the
    // STATIC DOM by walking every element's computed
    // `view-transition-name` and grouping by value.
    //
    // Two flavours of collision matter:
    //
    //   1. CSS-driven (the "site title" footgun) — a theme.json rule
    //      like `.wp-block-site-title { view-transition-name:
    //      fifty-site-title }` matches BOTH the header and the
    //      footer wordmark and assigns them the same name.
    //   2. PHP-driven (the "post-title appears twice" footgun) —
    //      a `render_block` filter naively assigns
    //      `fifty-post-{ID}-{kind}` to every `core/post-title`,
    //      and the same post ID renders in two block contexts on
    //      the same page (featured-products + post-template grid).
    //
    // Both are flagged here at error severity because the rendered
    // page IS broken — the next click silently aborts every
    // transition the theme tries to choreograph. Computed style is
    // the load-bearing source of truth (not the inline
    // `style=` attribute), because some rules apply via stylesheet
    // and inheritance.
    const vtSeen = new Map();  // name -> [{tag, id, classes}]
    document.querySelectorAll('*').forEach((el) => {
        const cs = window.getComputedStyle(el);
        const name = cs.viewTransitionName;
        if (!name || name === 'none' || name === 'auto') return;
        const arr = vtSeen.get(name) || [];
        arr.push({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            classes: (el.className && typeof el.className === 'string')
                ? el.className.split(/\s+/).filter(Boolean).slice(0, 4).join('.')
                : '',
        });
        vtSeen.set(name, arr);
    });
    for (const [name, els] of vtSeen.entries()) {
        if (els.length < 2) continue;
        const where = els.slice(0, 4).map((e) => {
            const cls = e.classes ? '.' + e.classes : '';
            const id = e.id ? '#' + e.id : '';
            return `${e.tag}${id}${cls}`;
        }).join(', ');
        push("error", "view-transition-name-collision",
             `Duplicate \`view-transition-name: ${name}\` on `
             + `${els.length} elements (${where}). The next `
             + `navigation will throw InvalidStateError and abort `
             + `every view transition the theme defines. Fix by `
             + `narrowing the selector (e.g. scope `
             + `\`.wp-block-site-title\` to a header/footer ancestor) `
             + `or by deduping per-post names in the render_block `
             + `filter.`,
             {vt_name: name, count: els.length});
    }

    // Captured measurements for the user-supplied INSPECT_SELECTORS.
    const wanted = args.inspectSelectors || [];
    for (const sel of wanted) {
        const els = Array.from(document.querySelectorAll(sel));
        const entry = {selector: sel, count: els.length, instances: []};
        for (const el of els.slice(0, 4)) {
            const r = el.getBoundingClientRect();
            const cs = window.getComputedStyle(el);
            entry.instances.push({
                width: Math.round(r.width),
                height: Math.round(r.height),
                visible: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none',
                display: cs.display,
                grid_template_columns: cs.gridTemplateColumns,
                min_width: cs.minWidth,
                max_width: cs.maxWidth,
            });
        }
        if (els.length === 0) {
            entry.missing = true;
            // Missing inspect selectors are usually a reason to update
            // snap_config.py rather than a real bug, so info-level only.
            push("info", "inspect-selector-missing",
                 `Selector \`${sel}\` matched 0 elements on this page.`,
                 {selector: sel});
        } else {
            // Surface obviously narrow sidebar-ish elements.
            for (const inst of entry.instances) {
                const looksLikeSidebar = /sidebar|aside/i.test(sel);
                if (looksLikeSidebar && inst.visible && inst.width > 0 && inst.width < 200 && vw >= 782) {
                    push("error", "narrow-sidebar",
                         `\`${sel}\` rendered ${inst.width}px wide on a ${vw}px viewport (expected >= 300px sidebar).`,
                         {selector: sel, element_width: inst.width, viewport_width: vw});
                }
            }
        }
        out.selectors.push(entry);
    }

    return out;
}
"""


def _is_known_noise(text: str) -> bool:
    """KNOWN_NOISE_SUBSTRINGS is sourced from snap_config.py so adding a
    noise filter is a one-line config edit — no snap.py change needed."""
    return any(s in text for s in KNOWN_NOISE_SUBSTRINGS)


# ---------------------------------------------------------------------------
# axe-core a11y vendor + injector
# ---------------------------------------------------------------------------
AXE_VERSION = "4.10.0"
AXE_VENDOR_PATH = REPO_ROOT / "bin" / "vendor" / "axe.min.js"
AXE_DOWNLOAD_URL = (
    f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
)
# Mapping from axe `impact` to our internal severity. Critical/serious
# block the build via the tiered gate; moderate/minor surface in the
# review without failing it. axe sometimes emits null impact for the
# experimental rules -- we treat those as info to avoid noise.
_AXE_IMPACT_TO_SEVERITY: dict[str, str] = {
    "critical": "error",
    "serious": "error",
    "moderate": "warn",
    "minor": "info",
}


def _ensure_axe_vendored() -> str | None:
    """Return axe-core source as a string, downloading once if needed.

    Returns None if the download failed AND no vendored copy exists
    (offline contributors get a one-line note rather than a build
    failure). Subsequent shoots reuse the vendored file.
    """
    if AXE_VENDOR_PATH.exists():
        return AXE_VENDOR_PATH.read_text(encoding="utf-8")
    AXE_VENDOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(AXE_DOWNLOAD_URL, timeout=30) as resp:
            data = resp.read().decode("utf-8")
    except Exception as e:
        print(f"  {YELLOW}warn:{RESET} could not download axe-core "
              f"({e}); a11y checks skipped.")
        return None
    AXE_VENDOR_PATH.write_text(data, encoding="utf-8")
    print(f"  {DIM}vendored axe-core {AXE_VERSION} to "
          f"{AXE_VENDOR_PATH.relative_to(REPO_ROOT)}{RESET}")
    return data


def _run_axe(page, axe_source: str) -> dict:
    """Inject axe-core into the page and return the violations report.

    Errors are swallowed and returned as a one-key dict so a single
    shaky page doesn't kill the whole shoot.
    """
    try:
        page.evaluate(axe_source)
        # `resultTypes: ['violations']` skips the (much larger)
        # passes/incomplete/inapplicable arrays so the artifact stays
        # under ~50KB even for image-heavy pages.
        result = page.evaluate(
            "() => axe.run(document, {resultTypes: ['violations']})"
        )
    except Exception as e:
        return {"error": f"axe injection/run failed: {e}", "violations": []}
    return result if isinstance(result, dict) else {"violations": []}


def _axe_to_findings(axe_result: dict) -> list[dict]:
    """Translate an axe report's violations into our finding format."""
    out: list[dict] = []
    for v in axe_result.get("violations", []) or []:
        impact = (v.get("impact") or "minor").lower()
        sev = _AXE_IMPACT_TO_SEVERITY.get(impact, "info")
        rule = v.get("id", "unknown")
        nodes = v.get("nodes", []) or []
        # axe can flag dozens of nodes for the same rule (e.g.
        # color-contrast on a list of links). Collapse to a single
        # finding per rule with the count + first 3 selectors so the
        # review stays scannable.
        first_selectors = []
        for n in nodes[:3]:
            target = n.get("target", [])
            if target:
                first_selectors.append(" > ".join(map(str, target[0:1])))
        out.append({
            "severity": sev,
            "kind": f"a11y-{rule}",
            "message": (
                f"{v.get('help', rule)} ({len(nodes)} node(s))"
                + (f" — first: {first_selectors[0]}" if first_selectors else "")
            ),
            "axe_help_url": v.get("helpUrl", ""),
            "axe_impact": impact,
            "axe_node_count": len(nodes),
            "axe_first_selectors": first_selectors,
        })
    return out


def _attach_diagnostics(page) -> dict:
    """Wire console + pageerror + response listeners onto a Playwright
    page and return a dict that accumulates the captured events.

    The dict is mutated in-place by the listeners. Drain it after each
    navigation by reading + clearing its lists; we keep one accumulator
    per page rather than per route to avoid handler churn between
    routes (Playwright re-emits handler-add cost on every wiring).
    """
    bag: dict = {"console": [], "page_errors": [], "network_failures": []}

    def on_console(msg):
        try:
            t = msg.type
        except Exception:
            t = "log"
        if t in ("warning", "error"):
            try:
                text = msg.text[:600]
                if _is_known_noise(text):
                    return
                bag["console"].append({"type": t, "text": text})
            except Exception:
                pass

    def on_pageerror(err):
        try:
            text = str(err)[:600]
            if _is_known_noise(text):
                return
            bag["page_errors"].append(text)
        except Exception:
            pass

    def on_response(resp):
        try:
            status = resp.status
            if status >= 400:
                bag["network_failures"].append({
                    "status": status,
                    "url": resp.url,
                    "method": resp.request.method,
                })
        except Exception:
            pass

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)
    return bag


# ---------------------------------------------------------------------------
# Interactive flow dispatcher (Phase 3)
# ---------------------------------------------------------------------------
def _run_interaction(page, flow: Interaction) -> str | None:
    """Run a declarative interaction. Return None on success, or an
    error string. Each step swallows its own selector misses (the
    selectors in snap_config use commas to allow theme-specific
    fallbacks; we only fail the flow if every alternative is missing).
    """
    for i, step in enumerate(flow.steps):
        action = step.get("action")
        try:
            if action == "wait":
                page.wait_for_timeout(int(step.get("ms", 100)))
            elif action == "press":
                page.keyboard.press(step["key"])
            elif action == "click":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 3000)))
                el.click(timeout=int(step.get("timeout_ms", 3000)))
            elif action == "hover":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 2000)))
                el.hover(timeout=int(step.get("timeout_ms", 2000)))
            elif action == "focus":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 2000)))
                el.focus(timeout=int(step.get("timeout_ms", 2000)))
            elif action == "fill":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 2000)))
                el.fill(step.get("text", ""),
                        timeout=int(step.get("timeout_ms", 2000)))
            else:
                return f"step {i}: unknown action {action!r}"
        except Exception as e:
            return f"step {i} ({action} {step.get('selector', '')!r}): {e}"
    return None


def _capture_cell(
    *,
    page,
    bag: dict,
    axe_source: str | None,
    theme: str,
    vp: Viewport,
    slug: str,
    inspect: list[str],
    url: str,
    out_dir: Path,
    nav_error: str | None,
    extra_findings: list[dict] | None = None,
) -> dict:
    """Run heuristics + axe + console budget + screenshot for one cell.

    Returns the manifest-shaped dict for the caller to append. The
    cell's `<slug>.png`, `<slug>.html`, `<slug>.findings.json`, and
    optional `<slug>.a11y.json` are written under `out_dir`.
    `extra_findings` lets the interactive caller inject e.g. an
    `interaction-failed` finding so it shows up in the same review row.
    """
    out_path = out_dir / f"{slug}.png"
    html_path = out_dir / f"{slug}.html"
    findings_path = out_dir / f"{slug}.findings.json"
    a11y_path = out_dir / f"{slug}.a11y.json"

    findings: dict = {}
    try:
        findings = page.evaluate(
            _HEURISTICS_JS, {"inspectSelectors": inspect}
        )
    except Exception as e:
        findings = {"findings": [
            {"severity": "warn", "kind": "heuristics-failed",
             "message": f"Heuristics evaluation failed: {e}"},
        ], "selectors": []}
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as e:
        print(f"    {YELLOW}warn:{RESET} html capture: {e}")

    axe_findings: list[dict] = []
    if axe_source is not None:
        axe_result = _run_axe(page, axe_source)
        axe_findings = _axe_to_findings(axe_result)
        try:
            a11y_path.write_text(
                json.dumps(axe_result, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"    {YELLOW}warn:{RESET} a11y write: {e}")

    try:
        page.screenshot(path=str(out_path), full_page=True)
    except Exception as e:
        print(f"    {RED}fail:{RESET} screenshot: {e}")
        return {}

    warn_console = sum(
        1 for c in bag["console"]
        if c.get("type") == "warning"
        and not _is_known_noise(c.get("text", ""))
    )
    budget_findings: list[dict] = []
    cw_budget = BUDGETS.get("console_warning_count", {})
    cw_max = cw_budget.get("max")
    if cw_max is not None and warn_console > cw_max:
        budget_findings.append({
            "severity": cw_budget.get("severity", "info"),
            "kind": "console-warn-budget",
            "message": (
                f"{warn_console} console warnings on this cell "
                f"(>{cw_max}). Consider triaging."
            ),
            "count": warn_console, "max": cw_max,
        })

    base_findings = list(findings.get("findings", []))
    findings["findings"] = (
        base_findings + axe_findings + budget_findings + (extra_findings or [])
    )

    findings_payload = {
        **findings,
        "theme": theme,
        "viewport": vp.name,
        "route": slug,
        "url": url,
        "navigation_error": nav_error,
        "console": list(bag["console"]),
        "page_errors": list(bag["page_errors"]),
        "network_failures": list(bag["network_failures"]),
        "a11y_path": (
            str(a11y_path.relative_to(REPO_ROOT))
            if axe_source is not None and a11y_path.exists() else None
        ),
    }
    findings_path.write_text(
        json.dumps(findings_payload, indent=2), encoding="utf-8"
    )

    finds = findings.get("findings", [])
    err_count = sum(1 for f in finds if f.get("severity") == "error")
    warn_count = sum(1 for f in finds if f.get("severity") == "warn")
    if err_count or warn_count:
        col = RED if err_count else YELLOW
        print(f"    {col}flags:{RESET} {err_count} error / "
              f"{warn_count} warn ({slug})")

    return {
        "viewport": vp.name,
        "route": slug,
        "path": str(out_path.relative_to(REPO_ROOT)),
        "size_bytes": out_path.stat().st_size,
        "findings_path": str(findings_path.relative_to(REPO_ROOT)),
        "html_path": str(html_path.relative_to(REPO_ROOT)),
        "a11y_path": (
            str(a11y_path.relative_to(REPO_ROOT))
            if axe_source is not None and a11y_path.exists() else None
        ),
        "error_count": err_count,
        "warn_count": warn_count,
    }


def shoot_theme(
    theme: str,
    server_url: str,
    routes: list[Route],
    viewports: list[Viewport],
    out_root: Path,
) -> dict:
    """Drive Playwright across (route, viewport). Returns a manifest dict.

    For each (route, viewport) the framework writes:
      <slug>.png            full-page screenshot (animations frozen)
      <slug>.html           rendered HTML after networkidle + JS settle
      <slug>.findings.json  structured diagnostics:
        * viewport          {width, height, scrollWidth, scrollHeight}
        * findings[]        DOM heuristics (overflow, WC notices, broken
                             images, sidebar squeeze, debug output, etc.)
        * selectors[]       computed widths/grid for INSPECT_SELECTORS
        * console[]         browser console warnings + errors
        * page_errors[]     uncaught JS exceptions
        * network_failures[] HTTP responses with status >= 400

    Heuristics + capture happen inside `page.evaluate()`; nothing in
    them mutates the DOM that gets screenshotted, so the PNG and the
    findings reflect the same rendered state.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover -- guidance for first-run users
        raise SystemExit(
            "Playwright is not installed. Install with:\n"
            "  python3 -m pip install --user playwright\n"
            "  playwright install chromium\n"
            f"(import error: {e})"
        )

    manifest: dict = {"theme": theme, "shots": []}
    out_root.mkdir(parents=True, exist_ok=True)
    # Vendor axe-core once per process. Returned source is None when
    # the contributor is offline AND has no vendored copy; that case
    # disables a11y checks gracefully instead of failing the shoot.
    axe_source = _ensure_axe_vendored()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for vp in viewports:
                ctx = browser.new_context(
                    viewport={"width": vp.width, "height": vp.height},
                    device_scale_factor=1,
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/138.0.0.0 Safari/537.36"
                    ),
                )
                # `add_init_script` runs before any page script, but we
                # need _FREEZE_CSS injected as a stylesheet (not a
                # variable) so it applies to every navigation. The
                # init script wires that up via a <style> tag on
                # DOMContentLoaded so timed animations (font swap,
                # WC drawer slide) settle before our screenshot fires.
                ctx.add_init_script(
                    "(() => { const s = document.createElement('style');"
                    f" s.textContent = {json.dumps(_FREEZE_CSS)};"
                    " document.documentElement.appendChild(s); })();"
                )
                page = ctx.new_page()
                bag = _attach_diagnostics(page)
                vp_dir = out_root / vp.name
                vp_dir.mkdir(parents=True, exist_ok=True)
                for route in routes:
                    url = server_url + route.path
                    print(
                        f"  {DIM}{vp.name:7s}{RESET} "
                        f"{route.slug:18s} → {url}",
                        flush=True,
                    )
                    # Reset accumulators between routes so per-route
                    # findings only attribute their own console + net
                    # noise (cross-route bleed would confuse the
                    # report).
                    bag["console"].clear()
                    bag["page_errors"].clear()
                    bag["network_failures"].clear()
                    nav_error: str | None = None
                    try:
                        page.goto(url, wait_until="networkidle", timeout=45_000)
                    except Exception as e:
                        nav_error = str(e)
                        print(f"    {YELLOW}warn:{RESET} navigation: {e}")
                    # Small settle for late client renders (mini-cart
                    # hydration, font swap, WC checkout XHR).
                    page.wait_for_timeout(500)
                    # Wait for WooCommerce blocks loading skeletons to
                    # disappear before screenshotting. Without this the
                    # cart and checkout routes routinely shoot at a
                    # moment where the WC blocks store API call has
                    # finished (so `networkidle` fired) but React
                    # hasn't yet swapped the `.wc-block-components-
                    # skeleton` placeholder for the real markup, and
                    # the screenshot captures gray skeleton bars
                    # instead of the actual order summary, line items,
                    # subtotals, etc. Bug visible on every cart-
                    # filled / checkout-filled snap before this guard
                    # was added.
                    #
                    # `wait_for_function` returns true once the page
                    # has zero `.wc-block-components-skeleton`
                    # elements OR every remaining skeleton is hidden
                    # (display:none / visibility:hidden / opacity:0 —
                    # the form Phase A's premium hide-rule takes for
                    # the WC blocks loading mask).
                    #
                    # 6s timeout: long enough for a slow WC store-API
                    # round-trip on a cold playground boot, short
                    # enough that pages without skeletons don't slow
                    # the run noticeably (the predicate returns true
                    # on the FIRST evaluation when the DOM has no
                    # skeleton at all). Failures are swallowed (some
                    # blocks legitimately keep a skeleton up; we'd
                    # rather shoot the page than hang the run).
                    try:
                        page.wait_for_function(
                            """() => {
                                const skeletons = document.querySelectorAll(
                                    '.wc-block-components-skeleton, '
                                    + '.wc-block-components-skeleton__element'
                                );
                                if (skeletons.length === 0) return true;
                                return Array.from(skeletons).every((el) => {
                                    const cs = window.getComputedStyle(el);
                                    return (
                                        cs.display === 'none'
                                        || cs.visibility === 'hidden'
                                        || parseFloat(cs.opacity) === 0
                                    );
                                });
                            }""",
                            timeout=6_000,
                        )
                    except Exception:
                        # Skeleton still present after 6s — capture
                        # anyway so the reviewer sees the regression
                        # instead of the script hanging.
                        pass

                    # Static cell. Heuristics + axe + screenshot of the
                    # page in its initial-load state.
                    static_entry = _capture_cell(
                        page=page, bag=bag, axe_source=axe_source,
                        theme=theme, vp=vp, slug=route.slug,
                        inspect=INSPECT_SELECTORS.get(route.slug, []),
                        url=url, out_dir=vp_dir, nav_error=nav_error,
                    )
                    if static_entry:
                        manifest["shots"].append(static_entry)

                    # Interactive cells (Phase 3). Run any flows
                    # registered for this route + viewport. Each flow
                    # produces its own <route>.<flow>.* artifact set
                    # so reviewers can compare static vs interacted
                    # state side-by-side.
                    for flow in INTERACTIONS.get(route.slug, []):
                        if flow.viewports and vp.name not in flow.viewports:
                            continue
                        bag["console"].clear()
                        bag["page_errors"].clear()
                        bag["network_failures"].clear()
                        flow_slug = f"{route.slug}.{flow.name}"
                        print(f"    {DIM}↳ flow:{RESET} {flow.name} "
                              f"({flow.description})", flush=True)
                        flow_err = _run_interaction(page, flow)
                        # Settle after the interaction to let any XHR /
                        # transition finish before the screenshot.
                        page.wait_for_timeout(300)
                        extra: list[dict] = []
                        if flow_err:
                            extra.append({
                                "severity": "warn",
                                "kind": "interaction-failed",
                                "message": (
                                    f"Interaction `{flow.name}` failed: "
                                    f"{flow_err}"
                                ),
                                "interaction": flow.name,
                            })
                            print(f"    {YELLOW}warn:{RESET} flow "
                                  f"`{flow.name}`: {flow_err}")
                        flow_entry = _capture_cell(
                            page=page, bag=bag, axe_source=axe_source,
                            theme=theme, vp=vp, slug=flow_slug,
                            inspect=INSPECT_SELECTORS.get(route.slug, []),
                            url=url, out_dir=vp_dir, nav_error=nav_error,
                            extra_findings=extra,
                        )
                        if flow_entry:
                            flow_entry["interaction"] = flow.name
                            manifest["shots"].append(flow_entry)
                ctx.close()
        finally:
            browser.close()

    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Diff engine (Pillow per-pixel with anti-aliasing tolerance)
# ---------------------------------------------------------------------------
def diff_images(baseline_path: Path, current_path: Path, diff_out_path: Path,
                channel_tolerance: int = 8) -> dict:
    """Compare two PNGs. Returns {'changed_pct': float, 'changed_px': int,
    'total_px': int, 'baseline_size': (w,h), 'current_size': (w,h)}.

    Strategy:
      * If sizes differ, return changed_pct=100.0 (we don't try to
        align). The baseline should be regenerated when viewport sizes
        change.
      * Otherwise count pixels whose max per-channel delta exceeds
        `channel_tolerance` (default 8/255 ≈ 3%). Anti-aliasing,
        sub-pixel font rendering, and gradient banding can produce
        small deltas across thousands of pixels even when the design
        hasn't changed; the tolerance suppresses that noise.
      * The diff PNG visualises changed pixels in red on the current
        image so the agent can read the file and see WHERE the drift
        is, not just THAT it drifted.
    """
    from PIL import Image, ImageChops

    base = Image.open(baseline_path).convert("RGB")
    cur = Image.open(current_path).convert("RGB")
    if base.size != cur.size:
        # Render a side-by-side strip so the user can see both.
        from PIL import ImageDraw
        w = max(base.size[0], cur.size[0])
        h = base.size[1] + cur.size[1] + 30
        strip = Image.new("RGB", (w, h), (40, 40, 40))
        strip.paste(base, (0, 0))
        strip.paste(cur, (0, base.size[1] + 30))
        d = ImageDraw.Draw(strip)
        d.text((10, base.size[1] + 5),
               f"size mismatch: baseline {base.size} vs current {cur.size}",
               fill=(255, 200, 0))
        diff_out_path.parent.mkdir(parents=True, exist_ok=True)
        strip.save(diff_out_path)
        return {
            "changed_pct": 100.0,
            "changed_px": -1,
            "total_px": base.size[0] * base.size[1],
            "baseline_size": list(base.size),
            "current_size": list(cur.size),
            "size_mismatch": True,
        }

    raw_diff = ImageChops.difference(base, cur)
    # Per-pixel max channel delta, then threshold.
    bands = list(raw_diff.split())  # R, G, B
    px = bands[0].load()
    w, h = raw_diff.size
    changed = 0
    # Build an overlay starting from the current image; paint pixels
    # that exceed tolerance in red so the agent can see drift location.
    overlay = cur.copy()
    op = overlay.load()
    rp = bands[0].load()
    gp = bands[1].load()
    bp_ = bands[2].load()
    for y in range(h):
        for x in range(w):
            if max(rp[x, y], gp[x, y], bp_[x, y]) > channel_tolerance:
                changed += 1
                op[x, y] = (255, 0, 0)
    diff_out_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(diff_out_path)
    total = w * h
    return {
        "changed_pct": (changed / total) * 100.0 if total else 0.0,
        "changed_px": changed,
        "total_px": total,
        "baseline_size": list(base.size),
        "current_size": list(cur.size),
        "size_mismatch": False,
    }


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------
def cmd_serve(args: argparse.Namespace) -> int:
    """Boot a single theme's playground and block until Ctrl-C.

    Useful when the agent wants to drive the site interactively via the
    cursor-ide-browser MCP, since that MCP CAN navigate to a localhost
    URL (it just can't run playground.wordpress.net's wasm engine).
    """
    theme = args.theme
    port = args.port
    print(f"Booting {GREEN}{theme}{RESET} on port {port or '(auto)'}...")
    # `serve` is the interactive subcommand; --login keeps the agent and
    # the user logged-in for cursor-ide-browser MCP poking and /wp-admin
    # access. `shoot` overrides this to capture logged-out visitor view.
    server = boot_server(theme, port=port, verbosity=args.verbosity, login=True)
    try:
        wait_for_server(server)
        print(f"\n{GREEN}Ready{RESET}: {server.url}/")
        print(f"  Login at: {server.url}/wp-admin/  (admin / password)")
        print(f"  Logs streaming to: {server.log_path}")
        print("  Press Ctrl-C to stop.\n")
        try:
            server.proc.wait()
        except KeyboardInterrupt:
            print("\nStopping...")
    finally:
        kill_server(server)
    return 0


def _shoot_one_theme(theme: str, routes: list[Route],
                     viewports: list[Viewport], port: int | None,
                     verbosity: str) -> tuple[str, str | None]:
    """Worker used by both the serial and concurrent shoot paths.

    Returns (theme, error) -- error is None on success, otherwise the
    exception message. We never raise here so a single bad theme
    doesn't abort the whole sweep.
    """
    out_root = SNAPS_DIR / theme
    try:
        with running_server(theme, port=port, verbosity=verbosity) as server:
            shoot_theme(theme, server.url, routes, viewports, out_root)
    except SystemExit as e:
        return theme, f"failed: {e}"
    except Exception as e:
        return theme, f"crashed: {e}"
    return theme, None


def cmd_shoot(args: argparse.Namespace) -> int:
    """Boot, capture, kill -- repeated per theme.

    Default is serial. `--concurrency=N` boots up to N themes in
    parallel (each on its own port chosen via find_free_port) which
    drops a 4-theme sweep from ~16min to ~4min. The cost is RAM (each
    Playground worker eats ~400MB) and CPU during the screenshot pass.

    `--changed` (Phase 5) restricts the sweep to themes whose files
    changed since `--changed-base` (default = uncommitted tree). When
    bin/* changed (framework-wide), the smart filter falls back to
    --all so we don't ship a stale sweep after a heuristic update.
    """
    if getattr(args, "changed", False):
        affected = _changed_themes(getattr(args, "changed_base", None))
        if affected is None:
            print(f"{DIM}--changed: framework files touched, "
                  f"falling back to all themes.{RESET}")
            themes = discover_themes()
        elif not affected:
            print(f"{GREEN}--changed: no theme files changed, nothing to shoot.{RESET}")
            return 0
        else:
            themes = affected
            print(f"{DIM}--changed: shooting only {', '.join(themes)}.{RESET}")
    elif args.all:
        themes = discover_themes()
    else:
        themes = [args.theme] if args.theme else []
    if not themes:
        raise SystemExit("Pass a theme name or --all.")

    routes = filter_routes(args.routes or (sorted(QUICK_ROUTES) if args.quick else None))
    viewports = filter_viewports(args.viewports or (sorted(QUICK_VIEWPORTS) if args.quick else None))
    concurrency = max(1, getattr(args, "concurrency", 1) or 1)
    if concurrency > len(themes):
        concurrency = len(themes)

    print(
        f"Shooting {len(themes)} theme(s) × {len(routes)} route(s) × "
        f"{len(viewports)} viewport(s) = "
        f"{len(themes)*len(routes)*len(viewports)} screenshot(s)"
        f"  [concurrency={concurrency}]\n"
    )

    failures: list[tuple[str, str]] = []

    if concurrency == 1 or len(themes) == 1:
        for theme in themes:
            print(f"=== {GREEN}{theme}{RESET} ===")
            t, err = _shoot_one_theme(
                theme, routes, viewports, args.port, args.verbosity
            )
            if err:
                print(f"{RED}{t} {err}{RESET}")
                failures.append((t, err))
    else:
        # Parallel theme shoots. Use a thread pool because the worker
        # is dominated by subprocess + network I/O, not Python CPU
        # work; threads keep the impl simple (no need to pickle the
        # Playwright handles).
        import concurrent.futures
        print(f"{DIM}(parallel mode: per-theme logs in tmp/<theme>-server.log){RESET}\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            # `port=None` so each worker picks its own free port; the
            # find_free_port() call inside boot_server walks 9400-9499
            # and is concurrent-safe because the bind happens via
            # subprocess.Popen immediately after.
            futures = {
                ex.submit(_shoot_one_theme, theme, routes, viewports,
                          None, args.verbosity): theme
                for theme in themes
            }
            for fut in concurrent.futures.as_completed(futures):
                t, err = fut.result()
                if err:
                    print(f"{RED}=== {t}: {err} ==={RESET}")
                    failures.append((t, err))
                else:
                    print(f"=== {GREEN}{t}{RESET}: done ===")

    print()
    if failures:
        print(f"{RED}done with {len(failures)} failure(s).{RESET}")
        for t, err in failures:
            print(f"  {RED}{t}:{RESET} {err}")
        return 1
    print(f"{GREEN}done.{RESET} Snaps in {SNAPS_DIR.relative_to(REPO_ROOT)}/")
    print(
        f"      Run {DIM}python3 bin/snap.py report{RESET} for a "
        f"per-route findings summary."
    )
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """Promote tmp/snaps/<theme>/<vp>/<slug>.png -> tests/visual-baseline/...

    With no further args: copies all latest snaps. With explicit
    `theme [route [viewport]]`: copies just that subset. The destination
    tree mirrors the source layout so diffs are trivial path lookups.
    """
    if not SNAPS_DIR.exists():
        raise SystemExit(
            f"No snaps to promote at {SNAPS_DIR}. Run "
            f"`bin/snap.py shoot --all` first."
        )

    themes = [args.theme] if args.theme else discover_themes()
    promoted = 0
    for theme in themes:
        src_root = SNAPS_DIR / theme
        if not src_root.exists():
            continue
        for vp_dir in src_root.iterdir():
            if not vp_dir.is_dir():
                continue
            if args.viewport and vp_dir.name != args.viewport:
                continue
            for png in vp_dir.glob("*.png"):
                if args.route and png.stem != args.route:
                    continue
                rel = png.relative_to(SNAPS_DIR)
                dst = BASELINE_DIR / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(png, dst)
                promoted += 1
                print(f"  baselined: {rel}")
    print(f"\n{GREEN}done.{RESET} {promoted} baseline(s) updated under "
          f"{BASELINE_DIR.relative_to(REPO_ROOT)}/")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare latest snaps to baselines; print a summary table."""
    threshold = args.threshold
    if getattr(args, "changed", False):
        affected = _changed_themes(getattr(args, "changed_base", None))
        if affected is None:
            themes = discover_themes()
        elif not affected:
            print(f"{GREEN}--changed: no theme files changed, "
                  f"nothing to diff.{RESET}")
            return 0
        else:
            themes = affected
    else:
        themes = discover_themes() if args.all else ([args.theme] if args.theme else [])
    if not themes:
        raise SystemExit("Pass a theme name or --all.")

    rows: list[tuple] = []
    summary: dict = {"threshold_pct": threshold, "results": []}
    for theme in themes:
        snaps = SNAPS_DIR / theme
        baseline = BASELINE_DIR / theme
        if not snaps.exists():
            print(f"{YELLOW}skip{RESET} {theme}: no current snaps "
                  f"(run shoot first).")
            continue
        for vp_dir in sorted(snaps.iterdir()):
            if not vp_dir.is_dir():
                continue
            for png in sorted(vp_dir.glob("*.png")):
                rel = png.relative_to(SNAPS_DIR)
                base_path = BASELINE_DIR / rel
                diff_path = DIFFS_DIR / rel
                if not base_path.exists():
                    rows.append((theme, vp_dir.name, png.stem,
                                 None, "no-baseline", "—"))
                    continue
                result = diff_images(base_path, png, diff_path,
                                     channel_tolerance=args.channel_tolerance)
                state = (
                    "FAIL" if result["changed_pct"] > threshold else "ok"
                )
                rows.append((theme, vp_dir.name, png.stem,
                             result["changed_pct"], state,
                             str(diff_path.relative_to(REPO_ROOT))))
                summary["results"].append({
                    "theme": theme, "viewport": vp_dir.name,
                    "route": png.stem, **result, "state": state,
                })

    DIFFS_DIR.mkdir(parents=True, exist_ok=True)
    (DIFFS_DIR / "diff_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    fail_count = sum(1 for r in rows if r[4] == "FAIL")
    no_baseline = sum(1 for r in rows if r[4] == "no-baseline")
    print(f"\n{'theme':10s} {'viewport':9s} {'route':20s} "
          f"{'Δ%':>8s}  state   diff path")
    print("-" * 90)
    for theme, vp, route, pct, state, diff_path in rows:
        pct_s = f"{pct:7.3f}" if pct is not None else "    —  "
        col = (RED if state == "FAIL"
               else YELLOW if state == "no-baseline"
               else GREEN)
        print(f"{theme:10s} {vp:9s} {route:20s} {pct_s} "
              f"  {col}{state:10s}{RESET} {diff_path}")
    print("-" * 90)
    print(f"{len(rows)} compared, {fail_count} regression(s) above "
          f"{threshold}% threshold, {no_baseline} missing baseline.\n")
    if fail_count:
        print(f"{RED}FAILED{RESET}: open the diff PNGs above to see "
              f"which pixels changed.\n"
              f"If the changes are intentional, re-baseline with:\n"
              f"  python3 bin/snap.py baseline --all\n"
              f"or scope to a single cell:\n"
              f"  python3 bin/snap.py baseline <theme> --route=<slug> "
              f"--viewport=<name>")
        return 1
    return 0


_SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}


# Tier policy (Phase 1). Tiered gate:
#   * HARD-fail (gate="fail")  -> bin/check.py --visual exits 1
#       - any heuristic finding with severity "error"
#       - any uncaught JS error (page_errs, after KNOWN_NOISE_SUBSTRINGS)
#       - any HTTP 5xx response
#       - the cell crashed during heuristics evaluation (heuristics-failed
#         is severity "warn" per JS, but it implies the page broke during
#         our probe; we don't promote it to fail by itself, just count it)
#   * SOFT-warn (gate="warn")  -> exit 0 with a loud banner
#       - any heuristic "warn" or "info"
#       - HTTP 4xx (still surfaces real bugs, but lots of WC variation
#         HEAD probes legitimately 404 so we don't block on them)
#       - any console.error (after noise filter)
#       - cross-theme parity drift (Phase 4 adds these as "warn"-severity
#         findings, so the same accounting picks them up)
#   * pass                     -> green light
#
# The classification lives in one place so the per-theme rollup, the
# cross-theme rollup, and the STATUS line all agree. Bumping a category
# from soft to hard (e.g. when we trust 4xx-detection enough) is a
# one-line change here.
_GATE_RANK = {"pass": 0, "warn": 1, "fail": 2}


def _compute_gate(summary: dict) -> str:
    """Return 'pass' | 'warn' | 'fail' for a per-theme summary dict."""
    if (summary.get("errors", 0) > 0
            or summary.get("page_errs", 0) > 0
            or summary.get("net_5xx", 0) > 0):
        return "fail"
    if (summary.get("warns", 0) > 0
            or summary.get("infos", 0) > 0
            or summary.get("net_4xx", 0) > 0
            or summary.get("console_errs", 0) > 0):
        return "warn"
    return "pass"


def _worst_gate(gates: Iterable[str]) -> str:
    worst = "pass"
    for g in gates:
        if _GATE_RANK.get(g, 0) > _GATE_RANK[worst]:
            worst = g
    return worst


def _gate_badge(gate: str, summary: dict | None = None) -> str:
    """Markdown badge line used at the top of every review.md."""
    summary = summary or {}
    if gate == "fail":
        bits = []
        if summary.get("errors"):
            bits.append(f"{summary['errors']} error")
        if summary.get("page_errs"):
            bits.append(f"{summary['page_errs']} uncaught JS")
        if summary.get("net_5xx"):
            bits.append(f"{summary['net_5xx']} HTTP 5xx")
        return f"**GATE: FAIL** ({', '.join(bits) or 'see findings below'})"
    if gate == "warn":
        bits = []
        if summary.get("warns"):
            bits.append(f"{summary['warns']} warn")
        if summary.get("infos"):
            bits.append(f"{summary['infos']} info")
        if summary.get("net_4xx"):
            bits.append(f"{summary['net_4xx']} HTTP 4xx")
        if summary.get("console_errs"):
            bits.append(f"{summary['console_errs']} console err")
        return f"**GATE: WARN** ({', '.join(bits) or 'see findings below'})"
    return "**GATE: PASS**"


def _print_status(gate: str, source: str = "snap") -> None:
    """Final STATUS line so terminal scrapers + humans both see the verdict."""
    if gate == "fail":
        col = RED
    elif gate == "warn":
        col = YELLOW
    else:
        col = GREEN
    print(f"\n{col}STATUS: {gate.upper()}{RESET}  ({source})")


def _gather_findings(themes: list[str]) -> list[dict]:
    """Walk tmp/snaps/<theme>/<vp>/*.findings.json and return a flat
    list of (theme, viewport, route, payload) tuples for the report.
    """
    out: list[dict] = []
    for theme in themes:
        snaps = SNAPS_DIR / theme
        if not snaps.exists():
            continue
        for vp_dir in sorted(snaps.iterdir()):
            if not vp_dir.is_dir():
                continue
            for fp in sorted(vp_dir.glob("*.findings.json")):
                try:
                    payload = json.loads(fp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                payload["_path"] = str(fp.relative_to(REPO_ROOT))
                out.append(payload)
    return out


def _cross_theme_parity(per_theme_payloads: dict[str, list[dict]],
                        drift_pct: float = 25.0) -> list[dict]:
    """Flag (route, viewport, selector) triples where one theme's
    measurement drifts >drift_pct% from the median of the others.

    Catches "Selvedge's cart sidebar broke and we didn't notice
    because we were looking at Obel" -- the static-PNG diff only
    catches drift vs the SAME theme's baseline; this catches drift
    BETWEEN themes that should look broadly similar at the same
    layout level.

    Returns a flat list of finding-shaped dicts (severity, kind,
    message, theme, viewport, route) so the report can render them
    inline without a special-case template.
    """
    if len(per_theme_payloads) < 3:
        # Need at least 3 themes for a meaningful median (with 2, any
        # difference is trivially > median). 4 is the current count.
        return []

    # Group payloads by (viewport, route, selector) so we can compare
    # the same cell across themes.
    by_cell: dict[tuple[str, str], dict[str, dict]] = {}
    for theme, payloads in per_theme_payloads.items():
        for p in payloads:
            key = (p.get("viewport", ""), p.get("route", ""))
            by_cell.setdefault(key, {})[theme] = p

    out: list[dict] = []
    for (vp, route), per_theme in by_cell.items():
        if len(per_theme) < 3:
            continue
        # Selector-by-selector width comparison.
        selectors_seen: set[str] = set()
        for p in per_theme.values():
            for s in p.get("selectors", []):
                selectors_seen.add(s.get("selector", ""))
        for sel in selectors_seen:
            widths: dict[str, int] = {}
            for theme, p in per_theme.items():
                for s in p.get("selectors", []):
                    if s.get("selector") != sel:
                        continue
                    inst = (s.get("instances") or [{}])[0]
                    w = inst.get("width") or 0
                    if w > 0:
                        widths[theme] = w
            if len(widths) < 3:
                continue
            sorted_w = sorted(widths.values())
            median = sorted_w[len(sorted_w) // 2]
            if median == 0:
                continue
            for theme, w in widths.items():
                pct = abs(w - median) / median * 100.0
                if pct >= drift_pct:
                    out.append({
                        "severity": "warn",
                        "kind": "parity-drift-width",
                        "message": (
                            f"`{sel}` is {w}px on {theme} but the "
                            f"cross-theme median is {median}px "
                            f"({pct:.0f}% drift)."
                        ),
                        "theme": theme, "viewport": vp, "route": route,
                        "selector": sel,
                        "this_width": w, "median_width": median,
                    })
        # Finding-count parity: a theme that suddenly has 5x more
        # findings than its peers on the same route is probably
        # broken in a way the per-theme review missed.
        counts: dict[str, int] = {
            theme: len([f for f in p.get("findings", [])
                        if f.get("severity") in ("error", "warn")])
            for theme, p in per_theme.items()
        }
        cs = sorted(counts.values())
        median_c = cs[len(cs) // 2]
        if median_c >= 1:  # only meaningful when most themes have findings
            for theme, c in counts.items():
                if c >= median_c * 2 + 2:  # +2 floor avoids "1 vs 3" noise
                    out.append({
                        "severity": "warn",
                        "kind": "parity-drift-findings",
                        "message": (
                            f"{c} error/warn findings on {theme} for "
                            f"`{vp}/{route}` (cross-theme median {median_c})."
                        ),
                        "theme": theme, "viewport": vp, "route": route,
                        "this_count": c, "median_count": median_c,
                    })
    return out


def cmd_report(args: argparse.Namespace) -> int:
    """Aggregate `*.findings.json` into per-theme review markdown.

    Output:
      tmp/snaps/<theme>/review.md      human-readable triage list
      tmp/snaps/review.md              cross-theme rollup with the
                                       worst findings first
      tmp/snaps/review.json            machine-readable summary

    Severity buckets:
      * error  -- definitely broken (broken image, narrow sidebar,
                  PHP debug output, JS uncaught exception, 5xx response)
      * warn   -- likely a polish issue (alt missing, mid-word wrap,
                  WC info notice, 4xx response)
      * info   -- worth a glance (oversized image, missing inspect
                  selector)

    The report is written even when no findings exist so consumers
    can detect "ran cleanly" vs "never ran" from the file's mtime.
    """
    if args.theme:
        themes = [args.theme]
    elif getattr(args, "changed", False):
        affected = _changed_themes(getattr(args, "changed_base", None))
        if affected is None:
            themes = discover_themes()
        elif not affected:
            print(f"{GREEN}--changed: no theme files changed, "
                  f"nothing to report on.{RESET}")
            return 0
        else:
            themes = affected
    elif args.all:
        themes = discover_themes()
    else:
        # Default: report on whatever was last shot.
        themes = sorted(p.name for p in SNAPS_DIR.iterdir()
                        if p.is_dir() and p.name in discover_themes()) \
            if SNAPS_DIR.exists() else []
    if not themes:
        raise SystemExit(
            "No snaps to report on. Run `bin/snap.py shoot --all` first."
        )

    rollup: list[dict] = []
    cross_theme_findings: list[tuple[dict, dict]] = []
    write_md = args.format in ("md", "both")
    write_json = args.format in ("json", "both")

    # Phase 4: cross-theme parity. Compute once for the whole report
    # so per-theme rendering can attribute parity findings to the
    # right theme alongside its own findings.
    per_theme_payloads: dict[str, list[dict]] = {
        theme: _gather_findings([theme]) for theme in themes
    }
    parity_findings = _cross_theme_parity(per_theme_payloads)
    parity_by_theme: dict[str, list[dict]] = {}
    for f in parity_findings:
        parity_by_theme.setdefault(f["theme"], []).append(f)

    for theme in themes:
        payloads = per_theme_payloads.get(theme, [])
        if not payloads:
            continue
        # Splice parity findings into this theme's per-route payloads
        # so the existing accounting (route_summary, gate) catches
        # them automatically.
        for pf in parity_by_theme.get(theme, []):
            for p in payloads:
                if (p.get("viewport") == pf["viewport"]
                        and p.get("route") == pf["route"]):
                    p.setdefault("findings", []).append(pf)
                    break
        # Per-route severity totals.
        route_summary: list[dict] = []
        all_findings: list[tuple[dict, dict]] = []
        for p in payloads:
            finds = p.get("findings", [])
            err = sum(1 for f in finds if f.get("severity") == "error")
            warn = sum(1 for f in finds if f.get("severity") == "warn")
            info = sum(1 for f in finds if f.get("severity") == "info")
            # Split 4xx vs 5xx so the tier policy can hard-fail on 5xx
            # alone without also failing on the noisy WC variation HEAD
            # 404 probes that fire on every product page.
            net_4xx = sum(1 for nf in p.get("network_failures", [])
                          if 400 <= nf.get("status", 0) < 500)
            net_5xx = sum(1 for nf in p.get("network_failures", [])
                          if nf.get("status", 0) >= 500)
            net_fail = net_4xx + net_5xx
            page_err = sum(1 for pe in p.get("page_errors", [])
                           if not _is_known_noise(pe))
            console_err = sum(1 for c in p.get("console", [])
                              if c.get("type") == "error"
                              and not _is_known_noise(c.get("text", "")))
            route_summary.append({
                "viewport": p["viewport"], "route": p["route"],
                "error": err, "warn": warn, "info": info,
                "net_fail": net_fail, "net_4xx": net_4xx, "net_5xx": net_5xx,
                "page_err": page_err,
                "console_err": console_err,
                "url": p.get("url", ""),
            })
            for f in finds:
                all_findings.append((p, f))
                cross_theme_findings.append((p, f))

        all_findings.sort(key=lambda pf: (
            _SEVERITY_RANK.get(pf[1].get("severity", "info"), 9),
            pf[0].get("viewport", ""), pf[0].get("route", ""),
            pf[1].get("kind", ""),
        ))

        # Per-theme summary used by both the rollup row and the gate
        # decision. Built once here so the badge at the top of review.md,
        # the JSON, and the cross-theme rollup all agree.
        theme_summary = {
            "theme": theme,
            "errors": sum(r["error"] for r in route_summary),
            "warns": sum(r["warn"] for r in route_summary),
            "infos": sum(r["info"] for r in route_summary),
            "page_errs": sum(r["page_err"] for r in route_summary),
            "console_errs": sum(r["console_err"] for r in route_summary),
            "net_fails": sum(r["net_fail"] for r in route_summary),
            "net_4xx": sum(r["net_4xx"] for r in route_summary),
            "net_5xx": sum(r["net_5xx"] for r in route_summary),
        }
        gate = _compute_gate(theme_summary)
        theme_summary["gate"] = gate

        # Per-theme markdown.
        lines: list[str] = []
        lines.append(f"# {theme} — visual review\n")
        # GATE badge is the first thing humans + agents see, so a
        # "FAIL" never gets buried under tables.
        lines.append(f"{_gate_badge(gate, theme_summary)}\n")
        lines.append(
            f"_Generated by `bin/snap.py report` from "
            f"`tmp/snaps/{theme}/**/*.findings.json`._\n"
        )
        lines.append("## Per-route summary\n")
        lines.append("| viewport | route | err | warn | info | 4xx | 5xx | console err | url |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
        for r in route_summary:
            lines.append(
                f"| {r['viewport']} | {r['route']} | {r['error']} | "
                f"{r['warn']} | {r['info']} | {r['net_4xx']} | "
                f"{r['net_5xx']} | {r['console_err']} | `{r['url']}` |"
            )
        lines.append("")

        if all_findings:
            lines.append("## Findings (worst first)\n")
            for p, f in all_findings:
                sev = f.get("severity", "info").upper()
                kind = f.get("kind", "")
                msg = f.get("message", "")
                lines.append(
                    f"- **{sev}** `{p['viewport']}/{p['route']}` "
                    f"`{kind}`: {msg}"
                )
            lines.append("")
        else:
            lines.append("## Findings\n\n_No DOM heuristic findings._\n")

        # Network failures + page errors get their own sections so a
        # 4xx that's not in `findings[]` still surfaces in triage.
        net_block: list[str] = []
        for p in payloads:
            for nf in p.get("network_failures", []):
                # Suppress the noisy WC variation HEAD probe spam.
                if nf.get("status") == 404 and "?" not in nf.get("url", ""):
                    pass
                net_block.append(
                    f"  * `{p['viewport']}/{p['route']}` "
                    f"{nf['method']} {nf['status']} {nf['url']}"
                )
        if net_block:
            lines.append("## HTTP failures (>=400)\n")
            lines.extend(net_block)
            lines.append("")

        page_err_block: list[str] = []
        for p in payloads:
            for pe in p.get("page_errors", []):
                if _is_known_noise(pe):
                    continue
                page_err_block.append(
                    f"  * `{p['viewport']}/{p['route']}`: {pe}"
                )
        if page_err_block:
            lines.append("## Uncaught JS errors\n")
            lines.extend(page_err_block)
            lines.append("")

        # Selector measurements -- one block per route that defined
        # INSPECT_SELECTORS, helpful for "what's the actual width?"
        # debugging without re-shooting.
        meas_block: list[str] = []
        for p in payloads:
            sels = p.get("selectors", [])
            if not sels:
                continue
            meas_block.append(
                f"\n### {p['viewport']}/{p['route']}\n"
            )
            meas_block.append("| selector | count | width × height (px) | display | grid-template-columns |")
            meas_block.append("|---|---:|---|---|---|")
            for s in sels:
                if s.get("missing"):
                    meas_block.append(
                        f"| `{s['selector']}` | 0 | _missing_ | — | — |"
                    )
                    continue
                inst = (s.get("instances") or [{}])[0]
                wxh = f"{inst.get('width', '?')} × {inst.get('height', '?')}"
                meas_block.append(
                    f"| `{s['selector']}` | {s['count']} | {wxh} | "
                    f"{inst.get('display', '?')} | "
                    f"`{inst.get('grid_template_columns', '?')}` |"
                )
        if meas_block:
            lines.append("## Inspector measurements\n")
            lines.extend(meas_block)
            lines.append("")

        theme_summary["report_path"] = (
            str((SNAPS_DIR / theme / "review.md").relative_to(REPO_ROOT))
        )
        theme_summary["routes"] = route_summary

        if write_md:
            (SNAPS_DIR / theme / "review.md").write_text(
                "\n".join(lines), encoding="utf-8"
            )
        if write_json:
            (SNAPS_DIR / theme / "review.json").write_text(
                json.dumps(theme_summary, indent=2), encoding="utf-8"
            )
        rollup.append(theme_summary)

    overall_gate = _worst_gate(r["gate"] for r in rollup) if rollup else "pass"

    # Cross-theme rollup.
    rollup_lines = ["# Snap review — all themes\n"]
    rollup_lines.append(f"{_gate_badge(overall_gate)}\n")
    rollup_lines.append("| theme | gate | errors | warns | infos | 4xx | 5xx | uncaught JS | console err | report |")
    rollup_lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rollup:
        rollup_lines.append(
            f"| {r['theme']} | {r['gate'].upper()} | {r['errors']} | "
            f"{r['warns']} | {r['infos']} | {r['net_4xx']} | "
            f"{r['net_5xx']} | {r['page_errs']} | {r['console_errs']} | "
            f"`{r['report_path']}` |"
        )
    if parity_findings:
        rollup_lines.append("\n## Cross-theme parity drift\n")
        rollup_lines.append(
            "_One theme's measurement diverged > 25% from the cross-theme "
            "median, OR one theme has > 2x the median error/warn count for "
            "the same route. Often the first sign of a regression that "
            "the per-theme baseline diff hasn't caught yet._\n"
        )
        for pf in parity_findings:
            rollup_lines.append(
                f"- `{pf['theme']}` `{pf['viewport']}/{pf['route']}` "
                f"`{pf['kind']}`: {pf['message']}"
            )

    SNAPS_DIR.mkdir(parents=True, exist_ok=True)
    if write_md:
        (SNAPS_DIR / "review.md").write_text(
            "\n".join(rollup_lines) + "\n", encoding="utf-8"
        )
    if write_json:
        (SNAPS_DIR / "review.json").write_text(
            json.dumps(
                {
                    "gate": overall_gate,
                    "themes": rollup,
                    "parity_drift": parity_findings,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # Print a terminal summary that mirrors the rollup.
    print(f"\n{'theme':10s} {'gate':>5s} {'err':>5s} {'warn':>5s} "
          f"{'info':>5s} {'4xx':>4s} {'5xx':>4s} {'js-err':>7s}  report")
    print("-" * 80)
    for r in rollup:
        gate = r["gate"]
        col = RED if gate == "fail" else YELLOW if gate == "warn" else GREEN
        print(f"{r['theme']:10s} {col}{gate.upper():>5s}{RESET} "
              f"{r['errors']:5d} {r['warns']:5d} {r['infos']:5d} "
              f"{r['net_4xx']:4d} {r['net_5xx']:4d} {r['page_errs']:7d}  "
              f"{r['report_path']}")
    print()
    print("Cross-theme rollup: tmp/snaps/review.md")
    if overall_gate == "warn" and getattr(args, "strict", False):
        # Loud banner so a passing-but-noisy run still gets attention,
        # even though we don't exit non-zero on warns.
        print(f"\n{YELLOW}{'!' * 70}{RESET}")
        print(f"{YELLOW}!!  WARN: snap report has {sum(r['warns'] for r in rollup)} "
              f"warning(s) and {sum(r['infos'] for r in rollup)} info finding(s). !!{RESET}")
        print(f"{YELLOW}!!  Build still passes, but please review tmp/snaps/review.md.    !!{RESET}")
        print(f"{YELLOW}{'!' * 70}{RESET}")
    _print_status(overall_gate, source="snap.py report")

    if getattr(args, "open", False) and write_md:
        review_md = SNAPS_DIR / "review.md"
        if review_md.exists() and sys.platform == "darwin":
            try:
                subprocess.run(["open", str(review_md)], check=False)
            except Exception:
                pass

    if getattr(args, "strict", False) and overall_gate == "fail":
        return 1
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Verify every dependency the snap pipeline needs.

    Exits 0 with a green tree when ready; 1 with a checklist of fixes
    on miss. Designed to be the first thing a new contributor (or a
    fresh CI run) calls before firing off a full sweep.

    Checks:
      * Python version >= 3.8
      * Pillow available (used by the diff engine)
      * Playwright available + Chromium installed
      * @wp-playground/cli reachable via npx (network OR cache)
      * axe-core vendored at bin/vendor/axe.min.js
      * Per-theme baselines exist under tests/visual-baseline/<theme>/
      * tmp/ writable
    """
    checks: list[tuple[str, bool, str]] = []  # (label, ok, hint)

    # Python
    py_ok = sys.version_info >= (3, 8)
    checks.append((
        f"Python {sys.version.split()[0]} >= 3.8",
        py_ok,
        "Upgrade Python to 3.8 or newer.",
    ))

    # Pillow
    try:
        import PIL  # noqa: F401
        checks.append(("Pillow (image diff engine) installed", True, ""))
    except ImportError:
        checks.append((
            "Pillow not installed",
            False,
            "pip install --user Pillow",
        ))

    # Playwright
    try:
        from playwright.sync_api import sync_playwright
        checks.append(("Playwright (Python) installed", True, ""))
        # Chromium binary
        try:
            with sync_playwright() as p:
                br = p.chromium.launch()
                br.close()
            checks.append(("Playwright Chromium runnable", True, ""))
        except Exception as e:
            checks.append((
                "Playwright Chromium NOT runnable",
                False,
                f"playwright install chromium  (error: {e})",
            ))
    except ImportError:
        checks.append((
            "Playwright not installed",
            False,
            "pip install --user playwright && playwright install chromium",
        ))

    # npx + @wp-playground/cli
    try:
        npx = subprocess.run(
            ["npx", "--version"], capture_output=True, text=True, check=False,
            timeout=10,
        )
        npx_ok = npx.returncode == 0
        checks.append((
            f"npx available ({(npx.stdout or '').strip()})",
            npx_ok,
            "Install Node.js (https://nodejs.org). npx ships with npm.",
        ))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        checks.append((
            "npx not found",
            False,
            "Install Node.js so npx can fetch @wp-playground/cli.",
        ))

    # axe-core
    if AXE_VENDOR_PATH.exists():
        checks.append((
            f"axe-core vendored at {AXE_VENDOR_PATH.relative_to(REPO_ROOT)}",
            True, "",
        ))
    else:
        checks.append((
            "axe-core NOT vendored (will download on first shoot)",
            True,  # not fatal -- snap.py downloads lazily
            "Run `python3 bin/snap.py shoot --quick obel` once with "
            "network access to vendor it.",
        ))

    # Baselines per theme
    for theme in discover_themes():
        bl = BASELINE_DIR / theme
        has_any = bl.exists() and any(bl.rglob("*.png"))
        checks.append((
            f"baseline present: tests/visual-baseline/{theme}/",
            has_any,
            f"Run `python3 bin/snap.py shoot {theme} && "
            f"python3 bin/snap.py baseline {theme}`.",
        ))

    # tmp writable
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        probe = TMP_DIR / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(("tmp/ writable", True, ""))
    except Exception as e:
        checks.append((
            "tmp/ NOT writable",
            False,
            f"Fix permissions on tmp/ ({e}).",
        ))

    # Render the tree.
    print(f"\n{DIM}Snap doctor — pre-flight checklist{RESET}")
    print("-" * 60)
    failed = 0
    for label, ok, hint in checks:
        if ok:
            print(f"  {GREEN}✓{RESET} {label}")
        else:
            failed += 1
            print(f"  {RED}✗{RESET} {label}")
            if hint:
                print(f"      {DIM}fix:{RESET} {hint}")
    print()
    if failed:
        print(f"{RED}doctor: {failed} check(s) failed.{RESET}")
        return 1
    print(f"{GREEN}doctor: ready.{RESET}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """shoot then diff then report --strict.

    The single command `bin/check.py --visual` calls. By default
    operates on every theme; `--changed` restricts to themes touched
    by uncommitted + base..HEAD diffs (Phase 5). Returns the worst of
    the three exit codes: shoot crashes (1), pixel-diff regression
    above threshold (1), or tiered-gate `fail` from report (1). Warns
    do NOT fail; report prints a loud banner and returns 0.
    """
    args.theme = None
    args.routes = None
    args.viewports = None
    args.quick = False
    args.concurrency = getattr(args, "concurrency", 1)
    # `--changed` overrides --all; the shoot/diff/report functions all
    # honor `args.changed` when set.
    if not getattr(args, "changed", False):
        args.all = True
    rc = cmd_shoot(args)
    if rc != 0:
        return rc
    args.theme = None
    diff_rc = cmd_diff(args)
    # Report always runs even when diff failed -- the heuristic data is
    # the most useful thing the agent has when something just broke.
    args.format = getattr(args, "format", "both")
    args.strict = True
    report_rc = cmd_report(args)
    return diff_rc or report_rc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="snap.py",
        description=(
            "Visual snapshot framework: boot Playground, capture pages "
            "with Playwright, diff against baselines."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s_serve = sub.add_parser("serve", help="Boot a theme and leave it running.")
    s_serve.add_argument("theme")
    s_serve.add_argument("--port", type=int, default=None)
    s_serve.add_argument("--verbosity", default="normal",
                         choices=["quiet", "normal", "debug"])
    s_serve.set_defaults(func=cmd_serve)

    s_shoot = sub.add_parser("shoot", help="Boot, capture, kill.")
    s_shoot.add_argument("theme", nargs="?", default=None,
                         help="Theme slug, or omit and use --all.")
    s_shoot.add_argument("--all", action="store_true",
                         help="Shoot every discoverable theme.")
    s_shoot.add_argument("--routes", nargs="+", default=None,
                         help="Subset of route slugs (default: all).")
    s_shoot.add_argument("--viewports", nargs="+", default=None,
                         help="Subset of viewport names (default: all).")
    s_shoot.add_argument("--quick", action="store_true",
                         help="Use snap_config.QUICK_* subsets only.")
    s_shoot.add_argument("--port", type=int, default=None,
                         help="Pin the playground port. Ignored when "
                         "--concurrency > 1 (each worker auto-picks).")
    s_shoot.add_argument("--concurrency", type=int, default=1,
                         help="Number of themes to shoot in parallel "
                         "(each spawns its own playground; ~400MB/worker). "
                         "Default 1 (serial).")
    s_shoot.add_argument("--verbosity", default="normal",
                         choices=["quiet", "normal", "debug"],
                         help="Forwarded to @wp-playground/cli; default "
                         "'normal' so blueprint progress lands in "
                         "tmp/<theme>-server.log for debugging boot hangs.")
    s_shoot.add_argument(
        "--changed", action="store_true",
        help="Smart: only shoot themes touched by uncommitted + "
        "<changed-base>..HEAD git changes. Framework changes (bin/*) "
        "fall back to all themes. Empty diff exits 0 immediately.",
    )
    s_shoot.add_argument(
        "--changed-base", default=None,
        help="Git base ref for --changed (e.g. main, HEAD~1). "
        "Default: only consider uncommitted changes.",
    )
    s_shoot.set_defaults(func=cmd_shoot)

    s_baseline = sub.add_parser(
        "baseline",
        help="Promote latest tmp/snaps to tests/visual-baseline/."
    )
    s_baseline.add_argument("theme", nargs="?", default=None)
    s_baseline.add_argument("--route", default=None)
    s_baseline.add_argument("--viewport", default=None)
    s_baseline.set_defaults(func=cmd_baseline)

    s_diff = sub.add_parser(
        "diff",
        help="Compare tmp/snaps to tests/visual-baseline.",
    )
    s_diff.add_argument("theme", nargs="?", default=None)
    s_diff.add_argument("--all", action="store_true")
    s_diff.add_argument("--threshold", type=float, default=0.5,
                        help="Max %% changed pixels before a cell fails.")
    s_diff.add_argument("--channel-tolerance", type=int, default=8,
                        help="Per-channel delta below which pixels are "
                        "treated as unchanged (anti-aliasing noise).")
    s_diff.add_argument("--changed", action="store_true",
                        help="Diff only themes touched by git diff (Phase 5).")
    s_diff.add_argument("--changed-base", default=None,
                        help="Git base ref for --changed.")
    s_diff.set_defaults(func=cmd_diff)

    s_check = sub.add_parser(
        "check",
        help="shoot --all then diff --all (used by bin/check.py --visual).",
    )
    s_check.add_argument("--threshold", type=float, default=0.5)
    s_check.add_argument("--channel-tolerance", type=int, default=8)
    s_check.add_argument("--port", type=int, default=None)
    s_check.add_argument("--concurrency", type=int, default=1)
    s_check.add_argument("--verbosity", default="quiet",
                         choices=["quiet", "normal", "debug"])
    s_check.add_argument(
        "--changed", action="store_true",
        help="Restrict shoot/diff/report to themes touched by git diff. "
        "Bin/* framework changes fall back to all themes.",
    )
    s_check.add_argument("--changed-base", default=None,
                         help="Git base ref for --changed (default: uncommitted).")
    s_check.add_argument(
        "--format", choices=["json", "md", "both"], default="both",
        help="Forwarded to the report stage.",
    )
    s_check.set_defaults(func=cmd_check)

    s_report = sub.add_parser(
        "report",
        help="Aggregate findings.json into review.md (per theme + rollup).",
    )
    s_report.add_argument("theme", nargs="?", default=None,
                          help="Theme slug; default reports on every "
                          "theme that has snaps in tmp/snaps/.")
    s_report.add_argument("--all", action="store_true",
                          help="Force reporting on every discovered theme.")
    s_report.add_argument(
        "--strict", action="store_true",
        help="Exit 1 when the tiered gate is FAIL (heuristic errors, "
        "uncaught JS, or HTTP 5xx). Warns still exit 0 with a loud "
        "banner. `bin/snap.py check` always passes --strict.",
    )
    s_report.add_argument(
        "--format", choices=["json", "md", "both"], default="both",
        help="Which artifacts to write: 'md' for review.md only, "
        "'json' for review.json only, 'both' (default) for both.",
    )
    s_report.add_argument("--changed", action="store_true",
                          help="Report only on themes touched by git diff.")
    s_report.add_argument("--changed-base", default=None,
                          help="Git base ref for --changed.")
    s_report.add_argument(
        "--open", action="store_true",
        help="After writing review.md, open it in the default app "
        "(macOS only; on other platforms this is a no-op).",
    )
    s_report.set_defaults(func=cmd_report)

    s_doctor = sub.add_parser(
        "doctor",
        help="Verify Playwright/Pillow/axe/baselines are ready.",
    )
    s_doctor.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
