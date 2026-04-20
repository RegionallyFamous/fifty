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
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Add `bin/` to sys.path so we can import snap_config when running this
# file from the repo root (the most common invocation).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from snap_config import (  # noqa: E402
    QUICK_ROUTES,
    QUICK_VIEWPORTS,
    ROUTES,
    THEME_ORDER,
    VIEWPORTS,
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
    except (urllib.error.URLError, socket.timeout, ConnectionError):
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


def shoot_theme(
    theme: str,
    server_url: str,
    routes: list[Route],
    viewports: list[Viewport],
    out_root: Path,
) -> dict:
    """Drive Playwright across (route, viewport). Returns a manifest dict.

    Each shot is full-page (Playwright stitches the viewport-height
    crops). We wait for `networkidle` so deferred WC blocks finish
    hydrating before capture; this matters most for cart/checkout where
    the order summary loads via XHR.
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

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for vp in viewports:
                ctx = browser.new_context(
                    viewport={"width": vp.width, "height": vp.height},
                    device_scale_factor=1,
                    # Pin a UA that excludes "HeadlessChrome" so WC's
                    # client-side redirects don't bounce us to a
                    # bot-friendly page.
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/138.0.0.0 Safari/537.36"
                    ),
                )
                page = ctx.new_page()
                vp_dir = out_root / vp.name
                vp_dir.mkdir(parents=True, exist_ok=True)
                for route in routes:
                    out_path = vp_dir / f"{route.slug}.png"
                    url = server_url + route.path
                    print(
                        f"  {DIM}{vp.name:7s}{RESET} "
                        f"{route.slug:18s} → {url}",
                        flush=True,
                    )
                    try:
                        page.goto(url, wait_until="networkidle", timeout=45_000)
                    except Exception as e:
                        # Capture whatever loaded so we can see the failure
                        # mode rather than aborting the whole sweep.
                        print(f"    {YELLOW}warn:{RESET} navigation: {e}")
                    # Small settle for late client renders (mini-cart
                    # hydration, font swap).
                    page.wait_for_timeout(500)
                    try:
                        page.screenshot(path=str(out_path), full_page=True)
                    except Exception as e:
                        print(f"    {RED}fail:{RESET} screenshot: {e}")
                        continue
                    manifest["shots"].append(
                        {
                            "viewport": vp.name,
                            "route": route.slug,
                            "path": str(out_path.relative_to(REPO_ROOT)),
                            "size_bytes": out_path.stat().st_size,
                        }
                    )
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
        print(f"  Press Ctrl-C to stop.\n")
        try:
            server.proc.wait()
        except KeyboardInterrupt:
            print("\nStopping...")
    finally:
        kill_server(server)
    return 0


def cmd_shoot(args: argparse.Namespace) -> int:
    """Boot, capture, kill -- repeated per theme."""
    if args.all:
        themes = discover_themes()
    else:
        themes = [args.theme] if args.theme else []
    if not themes:
        raise SystemExit("Pass a theme name or --all.")

    routes = filter_routes(args.routes or (sorted(QUICK_ROUTES) if args.quick else None))
    viewports = filter_viewports(args.viewports or (sorted(QUICK_VIEWPORTS) if args.quick else None))

    print(
        f"Shooting {len(themes)} theme(s) × {len(routes)} route(s) × "
        f"{len(viewports)} viewport(s) = "
        f"{len(themes)*len(routes)*len(viewports)} screenshot(s)\n"
    )

    failures = 0
    for theme in themes:
        print(f"=== {GREEN}{theme}{RESET} ===")
        out_root = SNAPS_DIR / theme
        try:
            with running_server(theme, port=args.port, verbosity=args.verbosity) as server:
                shoot_theme(theme, server.url, routes, viewports, out_root)
        except SystemExit as e:
            print(f"{RED}{theme} failed:{RESET} {e}")
            failures += 1
        except Exception as e:
            print(f"{RED}{theme} crashed:{RESET} {e}")
            failures += 1

    print()
    if failures:
        print(f"{RED}done with {failures} failure(s).{RESET}")
        return 1
    print(f"{GREEN}done.{RESET} Snaps in {SNAPS_DIR.relative_to(REPO_ROOT)}/")
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


def cmd_check(args: argparse.Namespace) -> int:
    """shoot --all then diff --all. The single command bin/check.py calls."""
    args.all = True
    args.theme = None
    args.routes = None
    args.viewports = None
    args.quick = False
    rc = cmd_shoot(args)
    if rc != 0:
        return rc
    args.theme = None
    return cmd_diff(args)


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
    s_shoot.add_argument("--port", type=int, default=None)
    s_shoot.add_argument("--verbosity", default="normal",
                         choices=["quiet", "normal", "debug"],
                         help="Forwarded to @wp-playground/cli; default "
                         "'normal' so blueprint progress lands in "
                         "tmp/<theme>-server.log for debugging boot hangs.")
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
    s_diff.set_defaults(func=cmd_diff)

    s_check = sub.add_parser(
        "check",
        help="shoot --all then diff --all (used by bin/check.py --visual).",
    )
    s_check.add_argument("--threshold", type=float, default=0.5)
    s_check.add_argument("--channel-tolerance", type=int, default=8)
    s_check.add_argument("--port", type=int, default=None)
    s_check.add_argument("--verbosity", default="quiet",
                         choices=["quiet", "normal", "debug"])
    s_check.set_defaults(func=cmd_check)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
