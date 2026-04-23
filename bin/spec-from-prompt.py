#!/usr/bin/env python3
"""Convert a free-form theme brief into a `bin/design.py` spec.json.

Why this exists
---------------
`bin/design.py --spec` requires a hand-authored JSON document. The
agent's mental model for a 50-theme batch run is "50 prompts in, 50
themes out", not "50 hand-crafted JSON files in." This script closes
the gap: feed it a prompt like

    "midcentury department store with warm cream + burnt orange,
     Bricolage Grotesque + Inter, 'parcel' microcopy"

and it produces a spec that `bin/design.py --spec` accepts.

How it works
------------
1. Build a system + user prompt that includes the spec schema (slugs,
   font slots, color rules) sourced from `bin/_design_lib.py`'s
   `KNOWN_COLOR_SLUGS` / `KNOWN_FONT_SLUGS` and a worked example
   (`example_spec()`).
2. Call Anthropic via `bin/_vision_lib.text_completion`, which reuses
   the vision lib's retry loop, spend ledger, and daily budget cap.
3. Parse the JSON out of the response, validate it via
   `_design_lib.validate_spec`. On validation failure, retry once with
   the validator's error messages appended to the prompt so the model
   can self-correct. Second failure exits non-zero with the model's
   last attempt for debugging.
4. Cache by SHA-256 of `(prompt, schema_version, model)`. Re-running
   the same prompt is free.
5. Write the validated spec to `--out` (default
   `tmp/specs/<slug>.json`) and print the path so `bin/design.py
   --prompt` (which shells out to this script) can read it.

Usage
-----
Generate a spec, write to default path::

    python3 bin/spec-from-prompt.py --prompt "midcentury department store..."

Generate to a specific path::

    python3 bin/spec-from-prompt.py --prompt "..." --out tmp/midcentury.json

Dry-run (validates schema text-construction without calling the API)::

    python3 bin/spec-from-prompt.py --prompt "..." --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from _design_lib import (  # noqa: E402
    KNOWN_COLOR_SLUGS,
    KNOWN_FONT_SLUGS,
    SLUG_PATTERN,
    example_spec,
    validate_spec,
)
from _vision_lib import (  # noqa: E402
    DEFAULT_DAILY_BUDGET_USD,
    DEFAULT_MODEL,
    ApiKeyMissingError,
    BudgetExceededError,
    text_completion,
)

# ---------------------------------------------------------------------------
# Schema version. Bump when the spec contract or the prompt itself changes
# in a way that should invalidate cached responses.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "v1"

CACHE_DIR = ROOT / "tmp" / "spec-from-prompt-cache"
DEFAULT_OUT_DIR = ROOT / "tmp" / "specs"


def build_system_prompt() -> str:
    """The system prompt pins the schema and the JSON-only output rule."""
    color_slugs = ", ".join(sorted(KNOWN_COLOR_SLUGS))
    font_slugs = ", ".join(sorted(KNOWN_FONT_SLUGS))
    example = json.dumps(example_spec(), indent=2)
    return (
        "You are an expert WordPress block-theme designer. Your only job "
        "is to convert a free-form theme brief into a strictly-validated "
        "JSON spec for the Fifty theme generator.\n\n"
        "Output rules:\n"
        "- Respond with EXACTLY one JSON object. No prose, no markdown "
        "fences, no preamble.\n"
        "- The object MUST satisfy this schema:\n"
        "  Required: slug (lowercase a-z0-9-, 2-39 chars, starting "
        "with a letter), name (non-empty string).\n"
        "  Optional: tagline (string), voice (string), source "
        "(theme slug to clone from; default 'obel'), palette "
        "(object: color-slug -> #hex), fonts (object: font-slug -> "
        "{family, fallback, google_font, weights}), layout_hints "
        "(array of strings).\n"
        f"  Allowed color slugs: {color_slugs}.\n"
        f"  Allowed font slugs: {font_slugs}.\n"
        "  Hex colors must match #RRGGBB or #RGB (#RRGGBBAA / #RGBA "
        "also accepted).\n"
        "- Slug must be unique and descriptive (e.g. 'midcentury', "
        "'aerocoastal'). Avoid generic words like 'modern' or 'clean'.\n"
        "- Palette should provide AT MINIMUM: base, surface, contrast, "
        "primary, primary-hover, accent. Add the rest if the brief "
        "warrants. Maintain WCAG AA contrast for primary on base.\n"
        "- Fonts: provide display + sans at minimum. google_font: true "
        "tells the generator to add the Google Fonts loader.\n"
        "- voice should be a one-paragraph description of the theme's "
        "microcopy register (e.g. 'warm midcentury department store: "
        "uses parcel for order, register for checkout').\n"
        "- layout_hints should be 2-5 short strings the human "
        "designer will use to restructure the homepage (e.g. "
        "'asymmetric hero with offset product image').\n\n"
        "Worked example (showing all fields):\n"
        f"{example}\n"
    )


def build_user_prompt(prompt: str, *, prior_errors: list[str] | None = None) -> str:
    """The user prompt is the brief itself + any prior validator
    errors (for the retry pass)."""
    parts = [
        "Generate a spec for the following theme brief.",
        "",
        "Brief:",
        prompt.strip(),
    ]
    if prior_errors:
        parts.extend(
            [
                "",
                "Your previous attempt FAILED schema validation. Fix these "
                "specific errors and re-emit the JSON object:",
                "",
            ]
        )
        parts.extend(prior_errors)
    parts.append("")
    parts.append("Respond with the JSON object only.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

# Models occasionally wrap the JSON in fenced blocks despite the system
# rule. Strip the fence if present, then parse. If both stripped + raw
# fail, we retry once via the caller; this regex only handles the
# common case.
_FENCED_JSON = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def extract_json(raw_text: str) -> str:
    """Best-effort extraction of a JSON object from a model response.

    Strips a single ```json fence if present; otherwise returns the
    text as-is so `json.loads` can render its own diagnostic."""
    text = raw_text.strip()
    m = _FENCED_JSON.match(text)
    if m:
        return m.group(1).strip()
    return text


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_key(prompt: str, model: str) -> str:
    payload = json.dumps(
        {"prompt": prompt, "schema": SCHEMA_VERSION, "model": model},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cache_lookup(prompt: str, model: str) -> dict | None:
    """Return cached spec dict for `(prompt, model)` if any. Cache
    hits cost $0 and survive across runs (prompt+schema+model fingerprint)."""
    key = _cache_key(prompt, model)
    f = CACHE_DIR / f"{key}.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cache_store(prompt: str, model: str, spec: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(prompt, model)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spec-from-prompt.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--prompt",
        required=True,
        type=str,
        help="Free-form theme brief.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Path to write the generated spec.json. Default: "
            "`tmp/specs/<slug>.json` derived from the model's chosen slug. "
            "Mutually exclusive with --out-dir."
        ),
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "Directory to write the spec into; the filename will be "
            "<slug>.json. Mutually exclusive with --out."
        ),
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            f"Anthropic model to use (default: {DEFAULT_MODEL}). The cache "
            "is keyed on this so swapping models forces a re-spend."
        ),
    )
    p.add_argument(
        "--budget-usd",
        type=float,
        default=DEFAULT_DAILY_BUDGET_USD,
        help=(
            "Daily budget cap forwarded to _vision_lib (default: "
            f"${DEFAULT_DAILY_BUDGET_USD:.2f}). Cache hits never count "
            "against the cap."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Don't call the API. Emits a fake spec derived from the "
            "example so `bin/design.py --prompt` smoke tests work without "
            "ANTHROPIC_API_KEY. The fake spec uses --slug-hint as its "
            "slug if provided."
        ),
    )
    p.add_argument(
        "--slug-hint",
        default=None,
        help="Override the slug in --dry-run output (default: 'demo-spec').",
    )
    p.add_argument(
        "--ignore-cache",
        action="store_true",
        help="Force a fresh API call even when a cached response exists.",
    )
    return p


def _resolve_out_path(args: argparse.Namespace, slug: str) -> Path:
    if args.out and args.out_dir:
        raise SystemExit("error: --out and --out-dir are mutually exclusive")
    if args.out:
        return args.out
    out_dir = args.out_dir or DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}.json"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    prompt = args.prompt.strip()
    if not prompt:
        print("error: --prompt must be non-empty", file=sys.stderr)
        return 2

    if args.dry_run:
        slug = (args.slug_hint or "demo-spec").lower()
        if not SLUG_PATTERN.match(slug):
            print(
                f"error: --slug-hint {slug!r} is not a valid theme slug",
                file=sys.stderr,
            )
            return 2
        spec = dict(example_spec())
        spec["slug"] = slug
        spec["name"] = spec.get("name", "Demo Spec")
        out_path = _resolve_out_path(args, slug)
        out_path.write_text(
            json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(str(out_path))
        return 0

    cached = None
    if not args.ignore_cache:
        cached = cache_lookup(prompt, args.model)
    if cached is not None:
        errs, _ = validate_spec(cached)
        if not errs:
            slug = str(cached.get("slug") or "")
            out_path = _resolve_out_path(args, slug)
            out_path.write_text(
                json.dumps(cached, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print("cache hit ($0)", file=sys.stderr)
            print(str(out_path))
            return 0
        print(
            "warn: cached spec failed validation; re-fetching.", file=sys.stderr
        )

    system_prompt = build_system_prompt()

    last_text = ""
    last_errors: list[str] | None = None
    for attempt in (1, 2):
        user_prompt = build_user_prompt(prompt, prior_errors=last_errors)
        try:
            resp = text_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=args.model,
                daily_budget_usd=args.budget_usd,
                label="spec-from-prompt",
            )
        except ApiKeyMissingError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except BudgetExceededError as e:
            print(f"error: {e}", file=sys.stderr)
            return 3

        last_text = resp.raw_text
        json_text = extract_json(resp.raw_text)
        try:
            raw = json.loads(json_text)
        except json.JSONDecodeError as e:
            last_errors = [f"  - JSON parse error: {e}"]
            print(
                f"attempt {attempt}: response was not valid JSON; retrying.",
                file=sys.stderr,
            )
            continue

        errs, validated = validate_spec(raw)
        if not errs and validated is not None:
            cache_store(prompt, args.model, raw)
            slug = validated.slug
            out_path = _resolve_out_path(args, slug)
            out_path.write_text(
                json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(
                f"spec generated (slug={slug}, cost=${resp.cost_usd:.4f}, "
                f"tokens={resp.input_tokens}+{resp.output_tokens})",
                file=sys.stderr,
            )
            print(str(out_path))
            return 0

        last_errors = [str(e) for e in errs]
        print(
            f"attempt {attempt}: spec failed validation ({len(errs)} error(s)); "
            "retrying with errors appended."
            if attempt == 1
            else f"attempt {attempt}: spec still failed validation.",
            file=sys.stderr,
        )

    print("error: spec-from-prompt could not produce a valid spec.", file=sys.stderr)
    print("Last validator errors:", file=sys.stderr)
    for err in (last_errors or []):
        print(err, file=sys.stderr)
    print("\nLast model output (for debugging):", file=sys.stderr)
    print(last_text, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
