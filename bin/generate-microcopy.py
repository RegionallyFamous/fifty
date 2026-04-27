#!/usr/bin/env python3
"""Generate per-theme microcopy overrides so no two themes share a visible string.

``bin/check.py``'s ``check_all_rendered_text_distinct_across_themes`` and
``check_pattern_microcopy_distinct`` fail when a newly-cloned theme still
carries Obel's verbatim body copy.  This script generates theme-appropriate
replacements for every duplicated string and writes them to
``<theme>/microcopy-overrides.json``, then calls
``bin/apply-microcopy-overrides.py`` to apply them to the source files.

Two generation modes
--------------------
**API mode** (when ``ANTHROPIC_API_KEY`` is set):
  Calls Claude to produce in-voice replacements.  Produces richer, more
  distinctive copy.

**Fallback mode** (no API key, or ``--no-api``):
  Uses a static rule table keyed by era/sector from the theme's spec.
  Covers the canonical duplicate strings that appear in every cloned theme.
  Sufficient to pass the automated gates; a copy-editing pass can upgrade
  later.

Output
------
``<theme>/microcopy-overrides.json``:  ``{needle: replacement, ...}``

Usage
-----
    python3 bin/generate-microcopy.py --theme agave
    python3 bin/generate-microcopy.py --theme agave --no-api
    python3 bin/generate-microcopy.py --all
    python3 bin/generate-microcopy.py --all --dry-run

Exit codes
----------
    0  Overrides written (or nothing to do).
    1  Fatal error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, iter_themes, resolve_theme_root

# ---------------------------------------------------------------------------
# Static fallback overrides (era × sector vocabulary)
# ---------------------------------------------------------------------------
# These cover every string that `check_all_rendered_text_distinct_across_themes`
# and `check_pattern_microcopy_distinct` flag for a freshly-cloned theme.
# The table is keyed by (era_keyword, sector_keyword) where the keywords are
# substrings of the spec's `voice` field.
#
# Priorities (applied in order):
#   1. Exact spec slug (highest specificity — add a slug key to override one theme)
#   2. (era, sector) tuple
#   3. era only
#   4. sector only
#   5. "_default" (catch-all)
#
# Values are dicts mapping obel's verbatim string to the replacement.
# Use DIFFERENT words, not just capitalisation — the check normalises case.
# ---------------------------------------------------------------------------

_FALLBACK_TABLE: dict[str | tuple[str, str], dict[str, str]] = {

    # -----------------------------------------------------------------------
    # Specific theme overrides (highest priority)
    # -----------------------------------------------------------------------

    "agave": {
        "a clear, confident headline": "a clear, considered statement",
        "a block-only woocommerce theme. composed entirely of core blocks, styled entirely from one design token file, and open-sourced at github.com/regionallyfamous/fifty.": "a beauty-first woocommerce theme. every surface distilled from one palette file, every token chosen by hand.",
        "Bottled morning — a cork-stoppered glass bottle of warm light, tagged in coral linen on a soft natural backdrop. The flagship product of the Wonders & Oddities demo catalogue.": "Bottled Morning — a hand-filled glass bottle of morning warmth, tagged in terracotta linen on cream. The hero product of our Wonders & Oddities range.",
        "Bottled Morning — a cork-stoppered glass bottle of warm light, tagged in coral linen on a soft natural backdrop. The flagship product of the Wonders & Oddities demo catalogue.": "Bottled Morning — a hand-filled glass bottle of morning warmth, tagged in terracotta linen on cream. The hero product of our Wonders & Oddities range.",
        "A short statement of intent.": "A considered statement of purpose.",
        "Two or three sentences explaining why your brand exists, what it makes, and why the maker cares.": "Two or three honest sentences about what we make, why we make it, and what drives us.",
        "Browse the shop, or pick up a thread you left in the journal.": "Browse the shop, or follow a thread from the journal.",
        "Your cart is rather empty.": "Your cart is waiting.",
        "Ready to make it yours?": "Ready to make it yours?  Take it home.",
        "a short receipt history, saved addresses, and your wishlist live behind one sign-in. already a customer?": "your order history, saved addresses, and wishlist live behind a single sign-in. already with us?",
        "A short receipt history, saved addresses, and your wishlist live behind one sign-in. Already a customer?": "Your order history, saved addresses, and wishlist live behind a single sign-in. Already with us?",
        "30-day returns": "30-day exchanges",
        "a short pause, then more": "a quiet pause, then more",
        "A tracking link is emailed when the carrier picks up your parcel.": "A tracking link lands in your inbox the moment the carrier collects your order.",
        "Can I track my order?": "Can I track where my order is?",
        "Do you ship internationally?": "Do you ship outside the country?",
        "Email us at help@example.com. We answer within one business day.": "Write to us at help@example.com. We reply within one working day.",
        "01 — Confirmation": "01 — Confirmed",
        "02 — Packed by hand": "02 — Prepared with care",
        "03 — On its way": "03 — Dispatched",
        "What happens next": "What follows now",
        "A receipt is on its way to your inbox. If it doesn't arrive, check your spam folder.": "A receipt is heading to your inbox. If it takes a while, your spam folder is worth checking.",
        "We'll wrap your order within one business day and email tracking the moment it ships.": "We'll prepare your order within one working day and send tracking as soon as it leaves.",
        "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Get in touch.</a>": "Most orders arrive in 2–5 working days. Questions? <a href=\"/contact/\">Write to us.</a>",
        "Free shipping": "Postage included",
        "Made to last": "Made to endure",
    },

    "agitprop": {
        "a clear, confident headline": "a bold, printed statement",
        "a block-only woocommerce theme. composed entirely of core blocks, styled entirely from one design token file, and open-sourced at github.com/regionallyfamous/fifty.": "a press-ready woocommerce theme. every surface set in type, every rule drawn in ink, and released at github.com/regionallyfamous/fifty.",
        "A short statement of intent.": "A printed declaration of intent.",
        "Two or three sentences explaining why your brand exists, what it makes, and why the maker cares.": "Two or three sentences set in bold type explaining the press, the work, and the cause behind it.",
        "Browse the shop, or pick up a thread you left in the journal.": "Browse the print shop, or pull a thread from the bulletin.",
        "Your cart is rather empty.": "Nothing in the press yet.",
        "Ready to make it yours?": "Pull the press. Take it home.",
        "a short receipt history, saved addresses, and your wishlist live behind one sign-in. already a customer?": "your print history, delivery addresses, and reserve list sit behind one login. returning subscriber?",
        "A short receipt history, saved addresses, and your wishlist live behind one sign-in. Already a customer?": "Your print history, delivery addresses, and reserve list sit behind one login. Returning subscriber?",
        "30-day returns": "30-day returns, no questions",
        "a short pause, then more": "a pause in production, then more",
        "A tracking link is emailed when the carrier picks up your parcel.": "A tracking reference is sent once the carrier collects your package.",
        "Can I track my order?": "Can I track my shipment?",
        "Do you ship internationally?": "Do you post outside the country?",
        "Email us at help@example.com. We answer within one business day.": "Post a note to help@example.com. We reply within one working day.",
        "01 — Confirmation": "01 — In press",
        "02 — Packed by hand": "02 — Wrapped flat",
        "03 — On its way": "03 — Posted out",
        "What happens next": "What the press does next",
        "A receipt is on its way to your inbox. If it doesn't arrive, check your spam folder.": "A receipt has been set and dispatched to your inbox. If it hasn't arrived, the spam folder may have intercepted it.",
        "We'll wrap your order within one business day and email tracking the moment it ships.": "We'll wrap and dispatch within one business day and post tracking the moment it leaves the studio.",
        "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Get in touch.</a>": "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Send a note.</a>",
        "Free shipping": "Postage on us",
        "Made to last": "Printed to last",
    },

    "apiary": {
        "a clear, confident headline": "a warm, nourishing headline",
        "a block-only woocommerce theme. composed entirely of core blocks, styled entirely from one design token file, and open-sourced at github.com/regionallyfamous/fifty.": "a honey-warm woocommerce theme. every surface drawn from one palette, every token chosen for warmth, and open-sourced at github.com/regionallyfamous/fifty.",
        "A short statement of intent.": "A nourishing statement of purpose.",
        "Two or three sentences explaining why your brand exists, what it makes, and why the maker cares.": "Two or three sentences about what we harvest, what we make from it, and why we believe in it.",
        "Browse the shop, or pick up a thread you left in the journal.": "Browse the store, or follow a line from the field notes.",
        "Your cart is rather empty.": "Your basket is still empty.",
        "Ready to make it yours?": "Ready to take some home?",
        "a short receipt history, saved addresses, and your wishlist live behind one sign-in. already a customer?": "your order history, saved addresses, and wishlist live behind a single sign-in. already with us?",
        "A short receipt history, saved addresses, and your wishlist live behind one sign-in. Already a customer?": "Your order history, saved addresses, and wishlist live behind a single sign-in. Already with us?",
        "30-day returns": "30-day return policy",
        "a short pause, then more": "a quiet season, then more",
        "A tracking link is emailed when the carrier picks up your parcel.": "A tracking link is sent the moment the courier collects your order.",
        "Can I track my order?": "How can I track my order?",
        "Do you ship internationally?": "Do you deliver outside the country?",
        "Email us at help@example.com. We answer within one business day.": "Write to help@example.com. We reply within one working day.",
        "01 — Confirmation": "01 — Received",
        "02 — Packed by hand": "02 — Packed with care",
        "03 — On its way": "03 — On its flight",
        "What happens next": "What comes next",
        "A receipt is on its way to your inbox. If it doesn't arrive, check your spam folder.": "A receipt is winging its way to your inbox. If it doesn't land, your spam folder is worth a peek.",
        "We'll wrap your order within one business day and email tracking the moment it ships.": "We pack your order within one working day and send tracking the moment it's collected.",
        "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Get in touch.</a>": "Most orders arrive in 2–5 working days. Questions? <a href=\"/contact/\">Reach out.</a>",
        "Free shipping": "Delivery included",
        "Made to last": "Made to keep",
    },

    "atomic": {
        "a clear, confident headline": "a bold, atomic-age headline",
        "a block-only woocommerce theme. composed entirely of core blocks, styled entirely from one design token file, and open-sourced at github.com/regionallyfamous/fifty.": "a mid-century woocommerce theme. every surface hand-drawn in the spirit of the space age, every token a nod to the era, and open-sourced at github.com/regionallyfamous/fifty.",
        "A short statement of intent.": "A bold declaration from the space age.",
        "Two or three sentences explaining why your brand exists, what it makes, and why the maker cares.": "Two or three sentences explaining the shop, what it stocks, and why the proprietor finds it irresistible.",
        "Browse the shop, or pick up a thread you left in the journal.": "Browse the shop floor, or follow a story from the log.",
        "Your cart is rather empty.": "Your haul is rather light.",
        "Ready to make it yours?": "Ready to bring one home?",
        "a short receipt history, saved addresses, and your wishlist live behind one sign-in. already a customer?": "your purchase record, saved addresses, and wish list sit behind one sign-in. returning customer?",
        "A short receipt history, saved addresses, and your wishlist live behind one sign-in. Already a customer?": "Your purchase record, saved addresses, and wish list sit behind one sign-in. Returning customer?",
        "30-day returns": "30-day send-backs",
        "a short pause, then more": "a brief intermission, then more",
        "A tracking link is emailed when the carrier picks up your parcel.": "A tracking number lands in your inbox the moment the carrier lifts your parcel.",
        "Can I track my order?": "Where is my order right now?",
        "Do you ship internationally?": "Do you ship to other countries?",
        "Email us at help@example.com. We answer within one business day.": "Hail us at help@example.com. We radio back within one business day.",
        "01 — Confirmation": "01 — Received loud and clear",
        "02 — Packed by hand": "02 — Stowed in the hold",
        "03 — On its way": "03 — Cleared for launch",
        "What happens next": "Mission status",
        "A receipt is on its way to your inbox. If it doesn't arrive, check your spam folder.": "Your receipt is incoming. If it doesn't land, check the junk folder — ground control may have intercepted it.",
        "We'll wrap your order within one business day and email tracking the moment it ships.": "We'll stow your order within one business day and beam tracking the instant it ships.",
        "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Get in touch.</a>": "Most orders splash down in 2–5 business days. Questions? <a href=\"/contact/\">Radio us.</a>",
        "Free shipping": "Free delivery",
        "Made to last": "Built to the decade",
    },

    "azulejo": {
        "a clear, confident headline": "a precise, glazed headline",
        "a block-only woocommerce theme. composed entirely of core blocks, styled entirely from one design token file, and open-sourced at github.com/regionallyfamous/fifty.": "a ceramics-first woocommerce theme. every surface reflects the glaze of the kiln, every pattern arranged by hand, and open-sourced at github.com/regionallyfamous/fifty.",
        "A short statement of intent.": "A considered declaration of craft.",
        "Two or three sentences explaining why your brand exists, what it makes, and why the maker cares.": "Two or three measured sentences explaining the workshop, what it fires, and what drives the potter.",
        "Browse the shop, or pick up a thread you left in the journal.": "Browse the gallery, or follow a line from the kiln notes.",
        "Your cart is rather empty.": "Your tray is empty.",
        "Ready to make it yours?": "Ready to take it from the kiln?",
        "a short receipt history, saved addresses, and your wishlist live behind one sign-in. already a customer?": "your order history, delivery addresses, and reserve list live behind one sign-in. returning collector?",
        "A short receipt history, saved addresses, and your wishlist live behind one sign-in. Already a customer?": "Your order history, delivery addresses, and reserve list live behind one sign-in. Returning collector?",
        "30-day returns": "30-day returns, no cracks",
        "a short pause, then more": "between firings, more arrives",
        "A tracking link is emailed when the carrier picks up your parcel.": "A tracking code is sent the moment the courier lifts your package.",
        "Can I track my order?": "How do I track my package?",
        "Do you ship internationally?": "Do you ship outside Portugal?",
        "Email us at help@example.com. We answer within one business day.": "Write to help@example.com. We reply within one working day.",
        "01 — Confirmation": "01 — Recorded in glaze",
        "02 — Packed by hand": "02 — Wrapped in tissue",
        "03 — On its way": "03 — Fired and dispatched",
        "What happens next": "What the kiln does next",
        "A receipt is on its way to your inbox. If it doesn't arrive, check your spam folder.": "Your receipt has been sent to your inbox. If it hasn't arrived, the spam folder is the first place to look.",
        "We'll wrap your order within one business day and email tracking the moment it ships.": "We wrap and pack your order within one working day and send tracking as soon as it leaves the workshop.",
        "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Get in touch.</a>": "Most orders arrive in 2–5 working days. Questions? <a href=\"/contact/\">Write to the workshop.</a>",
        "Free shipping": "Shipping without charge",
        "Made to last": "Fired to last",
    },

    # -----------------------------------------------------------------------
    # Generic fallback by era keyword (applied when no slug-specific entry)
    # -----------------------------------------------------------------------

    ("pre-1900", "ceramics"): {
        "a clear, confident headline": "a crafted, kiln-glazed headline",
        "Your cart is rather empty.": "Your tray holds nothing yet.",
        "30-day returns": "30-day returns from the kiln",
        "Free shipping": "Kiln-direct delivery",
    },
    ("mid-century", "gift"): {
        "a clear, confident headline": "a bold, boomerang-era headline",
        "Your cart is rather empty.": "Your haul is light.",
        "30-day returns": "30-day send-back policy",
        "Free shipping": "Postage-free delivery",
    },
}

_COMMON_STRINGS_TO_SKIP = {
    # Short strings that the check would ignore anyway
    "",
    "Free shipping",   # handled per-theme above
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_spec(theme_root: Path) -> dict:
    """Read the design spec from either the worktree path or tmp/specs/."""
    spec_candidates = [
        theme_root / "spec.json",
        MONOREPO_ROOT / "tmp" / "specs" / f"{theme_root.name}.json",
    ]
    for p in spec_candidates:
        if p.is_file():
            return json.loads(p.read_text())
    return {}


def _match_table(slug: str, voice: str) -> dict[str, str]:
    """Return the best substitution map for this theme from the fallback table."""
    # 1. Exact slug
    if slug in _FALLBACK_TABLE:
        return _FALLBACK_TABLE[slug]  # type: ignore[return-value]

    voice_lower = voice.lower()

    # 2. (era, sector) tuple
    era_keywords = ["pre-1900", "pre-1950", "mid-century", "contemporary", "modern"]
    sector_keywords = [
        "ceramics", "beauty", "food", "gift", "art-print", "coffee",
        "wine", "jewellery", "textile", "book", "pharmacy",
    ]
    matched_era = next((e for e in era_keywords if e in voice_lower), "")
    matched_sector = next((s for s in sector_keywords if s in voice_lower), "")

    if matched_era and matched_sector:
        key = (matched_era, matched_sector)
        if key in _FALLBACK_TABLE:
            return _FALLBACK_TABLE[key]  # type: ignore[return-value]

    # 3. Sector only
    if matched_sector:
        for (e, s), v in _FALLBACK_TABLE.items():  # type: ignore[misc]
            if isinstance(e, str) and s == matched_sector:  # type: ignore[misc]
                return v  # type: ignore[return-value]

    # 4. Era only
    if matched_era:
        for (e, s), v in _FALLBACK_TABLE.items():  # type: ignore[misc]
            if isinstance(e, str) and e == matched_era:  # type: ignore[misc]
                return v  # type: ignore[return-value]

    # 5. _default
    return _FALLBACK_TABLE.get("_default", {})  # type: ignore[return-value]


def _find_duplicates(theme_root: Path) -> dict[str, str]:
    """Return {needle: already_in_theme} for every string that conflicts."""
    slug = theme_root.name
    # Collect normalised strings from all OTHER themes
    others: dict[str, str] = {}  # normalised → first theme slug that has it
    for other in iter_themes(stages=()):
        if other.name == slug:
            continue
        for sub in ("templates", "parts", "patterns"):
            d = other / sub
            if not d.is_dir():
                continue
            for p in d.rglob("*"):
                if p.suffix not in {".html", ".php"}:
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for string in _extract_strings(text):
                    n = _normalise(string)
                    if n and n not in others:
                        others[n] = other.name

    # Now scan THIS theme for strings that collide
    duplicates: dict[str, str] = {}
    for sub in ("templates", "parts", "patterns"):
        d = theme_root / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.suffix not in {".html", ".php"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for string in _extract_strings(text):
                n = _normalise(string)
                if n and n in others:
                    duplicates[string] = others[n]
    return duplicates


_CONTENT_RE = re.compile(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"|<(?:h[1-6]|p|li|button|a|figcaption|blockquote)[^>]*>(.*?)</(?:h[1-6]|p|li|button|a|figcaption|blockquote)>', re.DOTALL)
_PHP_STR_RE = re.compile(r"""(?:__|_e|esc_html_e|esc_html__|esc_attr_e|esc_attr__)\(\s*['"]([^'"]+)['"]\s*[,)]""")


def _extract_strings(text: str) -> list[str]:
    out: list[str] = []
    for m in _CONTENT_RE.finditer(text):
        s = m.group(1) or m.group(2) or ""
        s = re.sub(r"<[^>]+>", "", s).strip()
        if s:
            out.append(s)
    for m in _PHP_STR_RE.finditer(text):
        out.append(m.group(1))
    return out


def _normalise(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(".,!?;:")
    s = s.replace("&amp;", "&").replace("&#8217;", "'").replace("&#8211;", "–")
    if len(s) < 12:
        return ""
    return s


def _generate_overrides_with_api(
    theme_root: Path,
    duplicates: dict[str, str],
    spec: dict,
    *,
    quiet: bool = False,
) -> dict[str, str]:
    """Call the Anthropic API to generate voice-appropriate replacements."""
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return {}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {}

    if not duplicates:
        return {}

    slug = theme_root.name
    voice = spec.get("voice", "")
    tagline = spec.get("tagline", "")

    pairs = "\n".join(f'  "{k}"' for k in sorted(duplicates)[:50])
    prompt = f"""\
You are rewriting marketing copy for a fictional WooCommerce storefront theme.

Theme name: {spec.get("name", slug)}
Voice brief: {voice}
Visual tagline: {tagline}

Rewrite EACH of the following strings so it:
1. Reads in the theme's voice (use its vocabulary, rhythm, and tone)
2. Is clearly different from the original (different words, not just capitalisation)
3. Is 12 or more characters long after stripping punctuation
4. Does NOT contain the original string as a substring (to prevent double-substitution)

Return ONLY a JSON object where every key is one of the input strings (verbatim) and
the value is the rewritten replacement.  Include ALL strings, even if only lightly
tweaked.  No explanation, no code fence.

Strings to rewrite:
{pairs}
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-claude-sonnet-4-5-20251022",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        overrides = json.loads(raw)
        if not quiet:
            print(f"  [{slug}] API generated {len(overrides)} override(s)")
        return overrides
    except Exception as exc:
        if not quiet:
            print(f"  [{slug}] API error: {exc}; falling back to static table")
        return {}


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def generate_overrides(
    theme_root: Path,
    *,
    no_api: bool = False,
    dry_run: bool = False,
    quiet: bool = False,
) -> int:
    """Generate and write ``<theme>/microcopy-overrides.json``.

    Returns number of overrides written (0 means nothing to do).
    """
    slug = theme_root.name
    spec = _load_spec(theme_root)
    voice = spec.get("voice", "")

    overrides: dict[str, str] = {}

    # Static table first (fast, offline)
    table = _match_table(slug, voice)
    if table:
        overrides.update(table)
        if not quiet:
            print(f"  [{slug}] static table: {len(overrides)} override(s)")

    # API generation for any remaining duplicates
    if not no_api:
        duplicates = _find_duplicates(theme_root)
        missing = {k: v for k, v in duplicates.items() if k not in overrides}
        if missing and not quiet:
            print(f"  [{slug}] {len(missing)} duplicate(s) not covered by static table; trying API")
        api_overrides = _generate_overrides_with_api(
            theme_root, missing, spec, quiet=quiet
        )
        overrides.update(api_overrides)

    if not overrides:
        if not quiet:
            print(f"  [{slug}] no overrides to write")
        return 0

    out_path = theme_root / "microcopy-overrides.json"
    if not dry_run:
        out_path.write_text(
            json.dumps(overrides, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if not quiet:
            print(f"  [{slug}] wrote {out_path.relative_to(MONOREPO_ROOT)}")
        # Apply immediately
        apply_script = MONOREPO_ROOT / "bin" / "apply-microcopy-overrides.py"
        if apply_script.is_file():
            cmd = [sys.executable, str(apply_script), "--theme", slug]
            rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
            if rc != 0 and not quiet:
                print(f"  [{slug}] WARN: apply-microcopy-overrides.py exited {rc}")
    else:
        if not quiet:
            print(f"  [{slug}] (dry-run) would write {len(overrides)} override(s)")

    return len(overrides)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--theme", metavar="SLUG")
    grp.add_argument("--all", action="store_true")
    parser.add_argument("--no-api", action="store_true",
                        help="Skip Anthropic API; use static table only.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.all:
        total = 0
        for theme_root in iter_themes(stages=()):
            total += generate_overrides(
                theme_root, no_api=args.no_api, dry_run=args.dry_run, quiet=args.quiet
            )
        print(f"Total: {total} override(s) across all themes.")
        return 0

    theme_root = resolve_theme_root(args.theme)
    generate_overrides(
        theme_root, no_api=args.no_api, dry_run=args.dry_run, quiet=args.quiet
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
