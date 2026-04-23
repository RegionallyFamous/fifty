#!/usr/bin/env python3
"""Render `vision:*` findings into a Markdown body for a PR comment.

Consumed by `.github/workflows/vision-review.yml`. Stdlib-only on
purpose: this script runs in CI on a fresh runner where adding a
dependency means another `pip install` step and another cache miss to
worry about.

Inputs
------
* `--root <dir>` : directory containing per-theme subdirs of
  downloaded artifacts. Layout matches what `actions/download-artifact`
  produces with `pattern: vision-*` and `merge-multiple: false`:
      tmp/snaps/
          vision-aero/
              desktop/
                  home.findings.json
                  home.review.png
                  ...
              vision-review.log
              vision-review.exit
          vision-chonk/
              ...
* `--out <file>` : path to write the rendered Markdown to.
* `--pr <number>` : PR number, only used for the link in the header.

Output
------
Markdown body. First line is always the sticky-comment marker
`<!-- vision-review:sticky -->`, so the workflow can locate / update
the existing comment on subsequent runs.

The body groups findings by theme, then by route+viewport, with one
table row per finding showing:

    severity | kind | message | rationale | remedy

If no `vision:*` findings exist across all themes, the body is the
"all clear" message (still useful to post so reviewers know the
review ran). If a theme's `vision-review.exit` is non-zero, the body
includes a per-theme "review crashed" callout instead of a clean
findings table for that theme.

Why not bundle this into snap-vision-review.py?
-----------------------------------------------
The reviewer is a per-PNG tool with no awareness of "all themes in
this PR". Aggregating across themes is a separate concern, and the
aggregator only ever runs in CI -- no point shipping it inside the
reviewer where it would drag in artifact-layout assumptions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

MARKER = "<!-- vision-review:sticky -->"

# Mirror of bin/_vision_lib.ALLOWED_KINDS minus the `vision:` prefix.
# Duplicated (rather than imported) on purpose: this script runs in
# the comment job's runner where bin/ may not even be on sys.path.
SEVERITY_ICON = {
    "error": "[error]",
    "warn": "[warn]",
    "info": "[info]",
}

SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}


def discover_themes(root: Path) -> list[str]:
    """Return the list of theme slugs we have artifacts for, sorted.

    Artifact dirs are named `vision-<slug>` per the workflow's
    `actions/upload-artifact` config. We strip the prefix and sort so
    the comment is stable across runs (otherwise a re-run could
    reorder the section headings and produce a noisy diff).
    """
    out = []
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.startswith("vision-"):
            out.append(child.name[len("vision-") :])
    return out


def theme_root(root: Path, slug: str) -> Path:
    return root / f"vision-{slug}"


def review_crashed(theme_dir: Path) -> tuple[bool, str]:
    """Return (crashed, log_excerpt). `crashed` is True when the
    reviewer's exit file is missing or non-zero.

    Missing exit file = the reviewer step itself didn't run (Playwright
    install failed, theme dir empty, etc.). We treat that as a crash
    so the comment makes the failure visible instead of silently
    showing an empty findings table.
    """
    exit_file = theme_dir / "vision-review.exit"
    log_file = theme_dir / "vision-review.log"
    if not exit_file.is_file():
        return True, "(no log file produced)"
    try:
        rc = int(exit_file.read_text(encoding="utf-8").strip() or "1")
    except ValueError:
        return True, "(exit file unreadable)"
    if rc == 0:
        return False, ""
    log_text = ""
    if log_file.is_file():
        # Last 30 lines is plenty for the "what blew up" diagnosis;
        # full log is in the artifact for anyone who wants to dig.
        log_text = "\n".join(log_file.read_text(encoding="utf-8").splitlines()[-30:])
    return True, log_text


def iter_findings(theme_dir: Path) -> Iterable[dict]:
    """Yield every `vision:*` finding from every findings.json under
    `theme_dir`, with the route + viewport derived from the file
    layout grafted on so the renderer doesn't have to guess later.
    """
    for fp in sorted(theme_dir.rglob("*.findings.json")):
        viewport = fp.parent.name
        route = fp.stem.removesuffix(".findings")
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for finding in payload.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            kind = finding.get("kind") or ""
            if not kind.startswith("vision:"):
                continue
            yield {
                "route": route,
                "viewport": viewport,
                "kind": kind,
                "severity": (finding.get("severity") or "info").lower(),
                "message": finding.get("message") or "",
                "rationale": finding.get("rationale") or "",
                "remedy_hint": finding.get("remedy_hint") or "",
                "bbox": finding.get("bbox"),
            }


def md_escape(s: str) -> str:
    """Tame characters that would break the Markdown table cell.

    GitHub's table renderer is strict about pipes and newlines inside
    cells; we replace them with their HTML escapes / a space so the
    table renders cleanly regardless of what the model wrote in
    `rationale`.
    """
    if not s:
        return ""
    return (
        s.replace("|", "\\|")
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def truncate(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "\u2026"


def render_theme_section(slug: str, theme_dir: Path) -> str:
    crashed, log_excerpt = review_crashed(theme_dir)
    if crashed:
        return (
            f"### `{slug}`\n\n"
            f"**Vision review did not complete cleanly.** "
            f"See the `vision-{slug}` workflow artifact for full logs.\n\n"
            f"<details><summary>Tail of vision-review.log</summary>\n\n"
            f"```\n{log_excerpt}\n```\n\n"
            f"</details>\n"
        )

    findings = list(iter_findings(theme_dir))
    if not findings:
        return f"### `{slug}`\n\nNo `vision:*` findings.\n"

    findings.sort(
        key=lambda f: (
            SEVERITY_RANK.get(f["severity"], 9),
            f["route"],
            f["viewport"],
            f["kind"],
        )
    )

    rows = ["| sev | route / viewport | kind | message | remedy hint |",
            "| --- | --- | --- | --- | --- |"]
    for f in findings:
        sev_label = SEVERITY_ICON.get(f["severity"], f["severity"])
        # Strip the `vision:` prefix in the table -- the section
        # heading and the column meaning already make it clear these
        # are vision findings, repeating the prefix in every cell is
        # noise.
        kind = f["kind"][len("vision:") :] if f["kind"].startswith("vision:") else f["kind"]
        location = f"`{f['route']}` / `{f['viewport']}`"
        message = md_escape(truncate(f["message"], 220))
        remedy = md_escape(truncate(f["remedy_hint"], 160)) or "_no hint_"
        rows.append(f"| {sev_label} | {location} | `{kind}` | {message} | {remedy} |")

    body = [f"### `{slug}`", "", *rows, ""]

    # Include rationales in a fold so the table stays scannable but
    # the model's reasoning is reachable for anyone debugging a
    # questionable finding. Skipped if every rationale is empty.
    if any(f["rationale"] for f in findings):
        body.append("<details><summary>Rationales</summary>\n")
        for f in findings:
            if not f["rationale"]:
                continue
            body.append(
                f"- **{f['route']} / {f['viewport']} / "
                f"`{f['kind']}`** — {md_escape(f['rationale'])}"
            )
        body.append("\n</details>\n")

    return "\n".join(body)


def render(root: Path, pr_number: str) -> str:
    themes = discover_themes(root)
    parts = [
        MARKER,
        "## Vision review",
        "",
        "Pixel-derived design critique from "
        "`bin/snap-vision-review.py` against each theme's "
        "`design-intent.md` rubric. **Findings are advisory** -- "
        "they are not gating, and humans + the in-Cursor agent decide "
        "what to act on. See `.cursor/rules/vision-findings.mdc` for "
        "the workflow.",
        "",
    ]
    if not themes:
        parts.append(
            "_No themes had artifacts to review (the PR may not have "
            "touched any theme source). Re-add the `design` label after "
            "pushing theme changes if you want a fresh review._"
        )
        return "\n".join(parts) + "\n"

    for slug in themes:
        parts.append(render_theme_section(slug, theme_root(root, slug)))
        parts.append("")

    parts.append(
        "<sub>Updated automatically by `.github/workflows/vision-review.yml` "
        f"for PR #{pr_number}.</sub>"
    )
    return "\n".join(parts) + "\n"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    p.add_argument("--root", required=True, type=Path,
                   help="dir containing vision-<slug>/ artifact dirs")
    p.add_argument("--out", required=True, type=Path,
                   help="path to write the rendered Markdown body")
    p.add_argument("--pr", required=True, type=str,
                   help="PR number (used in the footer link/text)")
    args = p.parse_args(argv)

    body = render(args.root, args.pr)
    args.out.write_text(body, encoding="utf-8")
    print(f"Wrote {len(body)} chars to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
