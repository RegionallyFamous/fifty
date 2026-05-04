#!/usr/bin/env python3
"""Emit a Miles-shaped handoff directory (`miles-ready.json` + `spec.json`).

**What this is**

Miles-led builds expect::

    <dir>/miles-ready.json   # {\"site_ready\": true, \"spec\": \"spec.json\"}
    <dir>/spec.json        # JSON that passes `validate_spec` + `validate_generation_safety`

In production, Miles writes these after you finish a site. This script
packages the *same artifact layout* so `bin/miles-bridge-to-spec.py` and
`bin/design.py build --miles-artifacts …` can run without a prior bench
concept (no `mockups/<slug>.meta.json`, no `vibes/Concepts/*.yaml`).

**Curated net-new demos**

``--from-demo <id>`` writes a hand-authored spec (palette, fonts, voice,
layout hints) that is not cloned from any existing Fifty concept queue
entry. Today only one demo ships:

* ``stellar-sextant`` — *Stellar Sextant*, a fictional shop for celestial
  navigation instruments, harbor charts, and brass workshop lamps
  (ink-navy base, brass accent, hydrographic-office diction).

For any other slug, pass ``--spec-json PATH`` to your own Miles-export-shaped
file (or iterate locally, then export from Miles for the canonical path).

Usage::

    python3 bin/bootstrap-miles-handoff.py --from-demo stellar-sextant \\
      --artifacts-dir tmp/miles-handoff-stellar-sextant

    python3 bin/miles-bridge-to-spec.py --slug stellar-sextant \\
      --name \"Stellar Sextant\" \\
      --artifacts-dir tmp/miles-handoff-stellar-sextant

    python3 bin/design.py build --miles-artifacts tmp/miles-handoff-stellar-sextant \\
      --miles-slug stellar-sextant --miles-name \"Stellar Sextant\"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from _design_lib import validate_generation_safety, validate_spec  # noqa: E402


def _demo_stellar_sextant() -> dict[str, object]:
    return {
        "slug": "stellar-sextant",
        "name": "Stellar Sextant",
        "tagline": "Celestial navigation, harbor charts, and brass you can trust at sea.",
        "voice": (
            "Measured hydrographic-office tone: call orders a 'ledger', "
            "the cart a 'manifest', checkout 'close the manifest', "
            "password link 'recover your ledger key', sort menu 'order of "
            "bearing', result counts 'entries sighted', totals ' reckonings', "
            "proceed button 'sign the manifest and sail on'. Use '·' as the "
            "required-field marker. No exclamation marks in customer-facing UI."
        ),
        "source": "obel",
        "palette": {
            "base": "#0a1020",
            "surface": "#121a2e",
            "subtle": "#1a2438",
            "muted": "#3d4f6f",
            "border": "#5a6d8f",
            "tertiary": "#8fa3c2",
            "secondary": "#c5d0e3",
            "contrast": "#f6f1e8",
            "primary": "#f6f1e8",
            "primary-hover": "#dcd6c8",
            "accent": "#d4a437",
            "accent-soft": "#2a2412",
            "success": "#3d8b6a",
            "warning": "#c98a2e",
            "error": "#c44c4c",
            "info": "#4a7dbd",
        },
        "fonts": {
            "display": {
                "family": "Libre Baskerville",
                "fallback": "Georgia, 'Times New Roman', serif",
                "google_font": True,
                "weights": [400, 700],
            },
            "sans": {
                "family": "Source Sans 3",
                "fallback": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                "google_font": True,
                "weights": [400, 600],
            },
        },
        "layout_hints": [
            "night-sky hero with a single brass instrument still-life and one chart texture",
            "narrow editorial column for shop story above a wide product rail",
            "footer with three columns: voyages (journal), instruments (categories), signals (social)",
        ],
    }


DEMOS: dict[str, dict[str, object]] = {
    "stellar-sextant": _demo_stellar_sextant(),
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--from-demo",
        metavar="ID",
        help=f"Curated net-new spec. Known ids: {', '.join(sorted(DEMOS))}.",
    )
    g.add_argument(
        "--spec-json",
        type=Path,
        help="Path to a Miles-shaped spec JSON (slug/name inside file must match --slug/--name).",
    )
    p.add_argument("--slug", required=True, help="Theme slug (must match spec JSON).")
    p.add_argument("--name", required=True, help='Theme display name (must match spec JSON "name").')
    p.add_argument(
        "--artifacts-dir",
        type=Path,
        required=True,
        help="Output directory (created if missing).",
    )
    args = p.parse_args(argv)

    slug = args.slug.strip().lower()
    name = args.name.strip()
    out_dir = args.artifacts_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_demo:
        demo_id = args.from_demo.strip().lower()
        if demo_id not in DEMOS:
            print(f"error: unknown demo {demo_id!r} (try: {', '.join(sorted(DEMOS))})", file=sys.stderr)
            return 2
        raw = dict(DEMOS[demo_id])
    else:
        raw = json.loads(args.spec_json.read_text(encoding="utf-8"))

    if raw.get("slug") != slug:
        print(
            f"error: spec slug {raw.get('slug')!r} does not match --slug {slug!r}",
            file=sys.stderr,
        )
        return 2
    if raw.get("name") != name:
        print(
            f"error: spec name {raw.get('name')!r} does not match --name {name!r}",
            file=sys.stderr,
        )
        return 2

    errors, spec = validate_spec(raw)
    if errors or spec is None:
        print("validate_spec failed:", file=sys.stderr)
        for e in errors:
            print(str(e), file=sys.stderr)
        return 2

    safety = validate_generation_safety(spec)
    if safety:
        print("validate_generation_safety failed:", file=sys.stderr)
        for e in safety:
            print(str(e), file=sys.stderr)
        return 2

    spec_path = out_dir / "spec.json"
    spec_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ready = {"site_ready": True, "spec": "spec.json"}
    (out_dir / "miles-ready.json").write_text(json.dumps(ready, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {spec_path}")
    print(f"wrote {out_dir / 'miles-ready.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
