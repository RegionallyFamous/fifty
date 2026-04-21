#!/usr/bin/env python3
"""
Personalize duplicated microcopy across themes so no two themes ship the
same user-visible string.

Why this exists
---------------
`bin/clone.py` copies obel's templates / parts / patterns into every new
theme verbatim. The clone rewrites only the slug + textdomain — the
actual *body copy*, *paragraph text*, *button labels*, *eyebrow strings*,
and *step lists* all carry over unchanged. The result is a row of demos
that visually differ but read like one shop with different paint jobs:

    "01 — Confirmation"  /  "02 — Packed by hand"  /  "03 — On its way"
    "What happens next"
    "We'll wrap your order within one business day and email tracking …"
    "The page you're looking for has moved, been removed, or never …"
    "We're putting the finishing touches on the shop. Leave your email …"

This script holds a per-theme substitution map keyed by theme slug. We
keep obel as the canonical baseline (it has the original copy by
definition) and rewrite every other theme into its own brand voice:

    aero      Y2K iridescent / signal / transmission / orbit / beam
    chonk     neo-brutalist / SLAB / STACK / hammered / uppercase
    lysholm   Nordic / hush / quiet / unhurried / considered
    selvedge  workwear / workshop / bench / mended / atelier

For each duplicated string we apply the replacement everywhere it
appears inside that theme's `templates/`, `parts/`, and `patterns/`
directories. Substitutions are literal (no regex on the haystack) and
idempotent — the script is safe to re-run after authoring more themes.

When you add a new theme, register a voice profile below and re-run.

Usage
-----
    python3 bin/personalize-microcopy.py            # apply
    python3 bin/personalize-microcopy.py --dry-run  # preview only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

THEMES_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("templates", "parts", "patterns")
SCAN_EXT = {".html", ".php"}


# ---------------------------------------------------------------------------
# Per-theme substitution maps. Keys are the EXACT byte-for-byte string
# that obel ships (or, for collisions where obel isn't involved, the
# canonical phrasing). Values are the replacement in that theme's voice.
#
# Each substitution is applied with `str.replace`, so the match must be
# unambiguous in the haystack — keep the keys long enough that they only
# match the intended span. Short labels ("Email address", "you@…") only
# get rewritten where the file actually uses them as visible UI copy.
# ---------------------------------------------------------------------------

VARIANTS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------
    # order-confirmation.html — three numbered steps + body copy
    # ------------------------------------------------------------------
    "Order received": {
        "aero":     "Signal received",
        "chonk":    "ORDER LOCKED IN",
        "lysholm":  "Order received, with thanks",
        "selvedge": "Order on the bench",
    },
    "01 — Confirmation": {
        "aero":     "01 — Signal locked",
        "chonk":    "01 — RECEIVED",
        "lysholm":  "01 — Noted",
        "selvedge": "01 — On the bench",
    },
    "02 — Packed by hand": {
        "aero":     "02 — Wrapped in shimmer",
        "chonk":    "02 — STACKED & TAPED",
        "lysholm":  "02 — Wrapped slowly",
        "selvedge": "02 — Boxed at the bench",
    },
    "03 — On its way": {
        "aero":     "03 — In orbit",
        "chonk":    "03 — OUT THE DOOR",
        "lysholm":  "03 — On its slow way",
        "selvedge": "03 — On the road",
    },
    "What happens next": {
        "aero":     "What's beaming next",
        "chonk":    "WHAT HAPPENS NOW",
        "lysholm":  "What follows, slowly",
        "selvedge": "What happens at the bench",
    },
    "A receipt is on its way to your inbox. If it doesn't arrive, check your spam folder.": {
        "aero":     "A glowing receipt is beaming to your inbox. If it never lands, peek in the spam folder.",
        "chonk":    "RECEIPT EMAILED. DOESN'T ARRIVE? CHECK SPAM.",
        "lysholm":  "A receipt is winding its way to your inbox. If it hasn't arrived yet, the spam folder is the next place to look.",
        "selvedge": "A receipt is being couriered to your inbox. If it doesn't land, the spam folder is worth a look.",
    },
    "We'll wrap your order within one business day and email tracking the moment it ships.": {
        "aero":     "We'll bundle your order within one business day and beam tracking the second it ships.",
        "chonk":    "WE PACK WITHIN ONE BUSINESS DAY. TRACKING EMAILED ON SHIP.",
        "lysholm":  "Your order is wrapped within one quiet business day, and we'll send tracking the moment it leaves.",
        "selvedge": "We pack at the bench within one business day and send tracking the moment it leaves.",
    },
    "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Get in touch.</a>": {
        "aero":     "Most orders land in 2–5 business days. Questions? <a href=\"/contact/\">Send a signal.</a>",
        "chonk":    "MOST ORDERS ARRIVE IN 2–5 DAYS. QUESTIONS? <a href=\"/contact/\">HOLLER.</a>",
        "lysholm":  "Most orders arrive in 2–5 unhurried business days. Questions? <a href=\"/contact/\">Write to us.</a>",
        "selvedge": "Most orders arrive in 2–5 business days. Questions? <a href=\"/contact/\">Drop us a line at the workshop.</a>",
    },
    "Shipping address": {
        "aero":     "Where it's beaming to",
        "chonk":    "SHIP TO",
        "lysholm":  "Sending to",
        "selvedge": "Where it's headed",
    },
    "Billing address": {
        "aero":     "Who it's billed to",
        "chonk":    "BILL TO",
        "lysholm":  "Billed to",
        "selvedge": "Billed to",
    },
    "You may also like": {
        "aero":     "You might also love",
        "chonk":    "MORE STUFF YOU'LL DIG",
        "lysholm":  "You may also enjoy",
        "selvedge": "More from the workshop",
    },

    # ------------------------------------------------------------------
    # 404.html — heading + body + buttons
    # ------------------------------------------------------------------
    "Page not found.": {
        "aero":     "Lost in the static.",
        "chonk":    "DEAD LINK.",
        "lysholm":  "Nothing here.",
        "selvedge": "Off the line.",
    },
    "The page you're looking for has moved, been removed, or never existed. Try the search below or head somewhere familiar.": {
        "aero":     "The signal you're after has drifted, dimmed, or never beamed. Try the search below or hop somewhere familiar.",
        "chonk":    "YOU HIT A WALL. THE PAGE MOVED, DIED, OR NEVER WAS. SEARCH BELOW OR HEAD HOME.",
        "lysholm":  "The page you came for has wandered off, slipped quietly aside, or was never written. Try the search below or step somewhere familiar.",
        "selvedge": "The page you came for has been mended, retired, or was never stitched. Try the search below or head back to the workshop.",
    },
    "Browse the shop": {
        "aero":     "Browse the catalog",
        "chonk":    "SHOP THE STACK",
        "lysholm":  "Browse the shelves",
        "selvedge": "Browse the line",
    },
    "Back to home": {
        "aero":     "Back to the lobby",
        "chonk":    "BACK HOME",
        "lysholm":  "Back to the front",
        "selvedge": "Back to the workshop",
    },

    # ------------------------------------------------------------------
    # parts/no-results.html
    # ------------------------------------------------------------------
    "There are no results to display. Try a different search or browse below.": {
        "aero":     "The signal came back empty. Try a different search or browse below.",
        "chonk":    "NOTHING FOUND. TRY ANOTHER SEARCH OR BROWSE BELOW.",
        "lysholm":  "Nothing turned up. Try a different search or browse below.",
        "selvedge": "Nothing came off the line. Try a different search or browse below.",
    },

    # ------------------------------------------------------------------
    # templates/page-coming-soon.html
    # ------------------------------------------------------------------
    "We're putting the finishing touches on the shop. Leave your email and we'll let you know the moment we open.": {
        "aero":     "We're tuning the signal. Leave your address and we'll beam you the moment we open.",
        "chonk":    "WE'RE STILL HAMMERING THE WALLS. DROP YOUR EMAIL AND WE'LL HOLLER WHEN WE OPEN.",
        "lysholm":  "We're quietly arranging the shelves. Leave your email and we'll let you know the moment the doors open.",
        "selvedge": "We're still finishing the seams. Leave your email and we'll send word the moment the workshop opens.",
    },

    # ------------------------------------------------------------------
    # templates/home.html — journal eyebrow + tagline
    # ------------------------------------------------------------------
    "Latest writing": {
        "aero":     "Latest transmissions",
        "chonk":    "NEW DISPATCHES",
        "lysholm":  "Latest dispatches",
        "selvedge": "From the bench",
    },
    "Writing on craft, commerce, and the things we make.": {
        "aero":     "Notes on signal, sparkle, and the catalog we beam.",
        "chonk":    "NOTES ON CRAFT. WORK. THE STUFF WE MAKE.",
        "lysholm":  "Slow notes on craft, commerce, and the things we make.",
        "selvedge": "Notes from the bench on craft, commerce, and the goods we make.",
    },

    # ------------------------------------------------------------------
    # templates/product-search-results.html
    # ------------------------------------------------------------------
    "Product search": {
        "aero":     "Catalog search",
        "chonk":    "SEARCH THE STACK",
        "lysholm":  "Browse the shelves",
        "selvedge": "Search the line",
    },

    # ------------------------------------------------------------------
    # patterns/newsletter.php — visible label + placeholder
    # ------------------------------------------------------------------
    # Keys are matched as substrings of the PHP source after the __()/
    # esc_attr_e() call site, so we use the literal string form here.
    # Email address  →  per-theme. We keep "you@example.com" as a
    # placeholder shape and rewrite the local-part to match the voice.
    "Email address": {
        "aero":     "Your signal",
        "chonk":    "YOUR EMAIL",
        "lysholm":  "Your address",
        "selvedge": "Your address",
    },
    "you@example.com": {
        "aero":     "name@orbit.example",
        "chonk":    "YOU@CHONK.EXAMPLE",
        "lysholm":  "name@quiet.example",
        "selvedge": "you@workshop.example",
    },

    # ------------------------------------------------------------------
    # patterns/value-props.php — three icon trio
    # ------------------------------------------------------------------
    "Free shipping": {
        "chonk":    "FREE SHIPPING",
        "lysholm":  "Shipping is on us",
        "selvedge": "Shipping at no charge",
    },
    "30-day returns": {
        "chonk":    "30-DAY RETURNS",
        "lysholm":  "Returns within 30 days",
        "selvedge": "30 days to return",
    },
    "Made to last": {
        "chonk":    "MADE TO LAST",
        "lysholm":  "Built to outlast",
        "selvedge": "Made to outlast you",
    },

    # ------------------------------------------------------------------
    # patterns/faq-accordion.php
    # ------------------------------------------------------------------
    "Frequently asked": {
        "chonk":    "FAQ",
        "lysholm":  "Quietly asked",
        "selvedge": "From the workbench",
    },

    # ------------------------------------------------------------------
    # patterns/cta-banner.php + hero / front-page CTAs
    # ------------------------------------------------------------------
    "Shop the catalog": {
        "chonk":    "SHOP THE STACK",
        "lysholm":  "Browse the catalog",
        "selvedge": "Shop the line",
    },
    "Shop the collection": {
        "aero":     "Beam the collection",
        "chonk":    "SHOP THE STACK",
        "lysholm":  "Browse the collection",
        "selvedge": "Shop the bench",
    },
    "Shop new arrivals →": {
        "lysholm":  "See what's newly stocked →",
    },

    # ------------------------------------------------------------------
    # patterns/testimonials.php + featured-products.php headings
    # ------------------------------------------------------------------
    "What customers say": {
        "chonk":    "WHAT FOLKS SAY",
        "lysholm":  "From quiet readers",
        "selvedge": "From the visiting log",
    },
    "This season": {
        "chonk":    "THIS SEASON",
        "lysholm":  "This quiet season",
        "selvedge": "On the bench this season",
    },

    # ------------------------------------------------------------------
    # patterns/hero-text.php / hero-image.php / hero-split.php +
    # selvedge front-page section
    # ------------------------------------------------------------------
    "New arrivals": {
        "aero":     "Just landed",
        "chonk":    "NEW STOCK",
        "lysholm":  "Newly stocked",
        "selvedge": "New off the bench",
    },

    # ------------------------------------------------------------------
    # category-tiles + front-page section heading
    # ------------------------------------------------------------------
    "Shop by category": {
        "chonk":    "SHOP BY DEPT.",
        "lysholm":  "Browse by collection",
        "selvedge": "Shop by trade",
    },

    # ------------------------------------------------------------------
    # parts/announcement-bar.html (lysholm + obel collide → keep obel,
    # rewrite lysholm)
    # ------------------------------------------------------------------
    "Free shipping on orders over $50": {
        "lysholm":  "Shipping on us above $50",
    },

    # ------------------------------------------------------------------
    # parts/footer.html copyright (lysholm + obel collide)
    # ------------------------------------------------------------------
    "© Site Title. All rights reserved.": {
        "lysholm":  "© Site Title. Every right held quietly.",
    },

    # ------------------------------------------------------------------
    # templates/single-product.html — long policy + care copy
    # ------------------------------------------------------------------
    "Standard shipping is free on orders over $50 and ships within 1–2 business days. Express delivery available at checkout.": {
        "aero":     "Standard signal is free on orders over $50 and ships in 1–2 business days. A faster orbit is available at checkout.",
        "lysholm":  "Free shipping on orders over $50, sent within 1–2 unhurried business days. Faster delivery is offered at checkout.",
        "selvedge": "Standard shipping is on us over $50 and leaves the workshop in 1–2 business days. Faster options at checkout.",
    },
    "Crafted from responsibly sourced materials and finished by hand. Wipe clean with a soft, dry cloth; avoid prolonged direct sunlight.": {
        "aero":     "Made from responsibly sourced materials and hand-finished with care. Wipe with a soft, dry cloth; keep out of long direct sun.",
        "lysholm":  "Worked from responsibly sourced materials and finished slowly by hand. Wipe with a soft, dry cloth; keep away from prolonged sun.",
        "selvedge": "Built from responsibly sourced materials and finished by hand at the workbench. Wipe with a soft, dry cloth; keep clear of long direct sun.",
    },

    # ------------------------------------------------------------------
    # patterns/hero-split.php — flagship product description (lysholm
    # + obel collide → rewrite lysholm)
    # ------------------------------------------------------------------
    "Bottled morning — a cork-stoppered glass bottle of warm light, tagged in coral linen on a soft natural backdrop. The flagship product of the Wonders & Oddities demo catalogue.": {
        "lysholm":  "Bottled Morning — a hand-stoppered glass bottle of soft Nordic light, tagged in pale linen on a bare cream backdrop. The flagship object of our quiet Wonders & Oddities catalogue.",
    },

    # ------------------------------------------------------------------
    # patterns/faq-accordion.php — shared question phrasing (lysholm
    # + selvedge collide → rewrite lysholm)
    # ------------------------------------------------------------------
    "What if it doesn't fit?": {
        "lysholm":  "What if it doesn't suit?",
    },

    # ------------------------------------------------------------------
    # templates/front-page.html — "From the journal" eyebrow (obel +
    # selvedge collide → rewrite selvedge)
    # ------------------------------------------------------------------
    "From the journal": {
        "selvedge": "From the workbench",
    },
}


def apply_for_theme(theme_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Apply VARIANTS for one theme. Returns (files_touched, subs_made)."""
    slug = theme_dir.name
    files_touched = 0
    subs_made = 0

    for sub in SCAN_DIRS:
        d = theme_dir / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_EXT:
                continue
            original = path.read_text(encoding="utf-8")
            updated = original
            file_subs = 0
            for needle, by_theme in VARIANTS.items():
                replacement = by_theme.get(slug)
                if replacement is None:
                    continue
                if needle not in updated:
                    continue
                count = updated.count(needle)
                updated = updated.replace(needle, replacement)
                file_subs += count
            if updated != original:
                files_touched += 1
                subs_made += file_subs
                if not dry_run:
                    path.write_text(updated, encoding="utf-8")
                rel = path.relative_to(theme_dir).as_posix()
                marker = "(dry-run)" if dry_run else ""
                print(f"  {slug:9s} {rel:50s} {file_subs} subs {marker}")

    return files_touched, subs_made


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the substitutions but don't write files.")
    args = parser.parse_args()

    themes = [
        p for p in sorted(THEMES_ROOT.iterdir())
        if p.is_dir() and (p / "theme.json").exists() and (p / "style.css").exists()
    ]
    if not themes:
        print("No themes found.", file=sys.stderr)
        return 2

    total_files = 0
    total_subs = 0
    for theme in themes:
        f, s = apply_for_theme(theme, args.dry_run)
        total_files += f
        total_subs += s

    label = "would touch" if args.dry_run else "touched"
    print(f"\n{label} {total_files} file(s) across {len(themes)} theme(s); "
          f"{total_subs} substitution(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
