#!/usr/bin/env python3
"""One-shot (re-runnable) string pass: rewrite Noir templates/parts/patterns that
still matched Selvedge after a bad clone. Keeps needles as exact file substrings."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOIR = ROOT / "noir"
SCAN = ("templates", "parts", "patterns")
EXT = {".html", ".php"}

# (needle, replacement) — longest needles first after sort below.
PAIRS: list[tuple[str, str]] = [
    (
        "Every piece in the collection is chosen against a single standard: does it improve with use? We source raw denim from Kojima, leather from Vermont, and wool from small family mills in the British Isles.",
        "Every piece in the Noir line is vetted on one question: does it look sharper under streetlight? We pull raw denim from Kojima, leather from Vermont, and wool from small family mills in the British Isles.",
    ),
    (
        "Ten goods from the new season, chosen for cloth, cut, and the way they settle into a life lived well. Raw materials. Honest craft.",
        "Ten goods from the new season, chosen for cloth, cut, and the way they carry shadow. Raw materials. Honest craft.",
    ),
    (
        "Standard shipping is on us over $50 and leaves the workshop in 1–2 business days. Faster options at checkout. Returns accepted within 30 days on unopened items in their original packaging.",
        "Standard shipping is on us over $50 and leaves the bureau in 1–2 business days. Faster options at checkout. Returns accepted within 30 days on unopened items in their original packaging.",
    ),
    (
        "Made in small batches by a workshop we know by name. Each piece carries the marks of its making — slight irregularities are not flaws but provenance. Numbered and tagged at the source.",
        "Made in small batches by a bureau we know by name. Each piece carries the marks of its making — slight irregularities are not flaws but provenance. Numbered and tagged at the source.",
    ),
    (
        "Shipping at no charge over $50, hand-wrapped and posted from the workshop within two days.",
        "Shipping at no charge over $50, hand-wrapped and posted from the bureau within two days.",
    ),
    (
        "Where each piece in the catalog comes from, who is at the loom, and what we keep cutting back to. Open at any time, no address required.",
        "Where each piece in the catalog comes from, who is at the loom, and what we keep cutting back to. Open at any hour, no address required.",
    ),
    (
        "Each piece numbered, signed, and sized to wear in for a decade or two.",
        "Each piece numbered, signed, and sized to wear in for a decade or two under sodium light.",
    ),
    (
        "A tracking link arrives in your inbox the moment the parcel leaves the workshop.",
        "A tracking wire hits your inbox the moment the crate leaves the loading dock.",
    ),
    (
        "Write us at hello@example.com — a maker reads every note and writes back inside a working day.",
        "Write us at hello@example.com — a night reader answers every note before the next shift change.",
    ),
    (
        "Yes — we ship worldwide. Rates calculate at checkout based on parcel weight and destination.",
        "Yes — we ship worldwide. Rates calculate at checkout based on crate weight and destination.",
    ),
    (
        "Each piece is wrapped at the bench within 1–2 days. Most parcels reach you inside the week.",
        "Each piece is wrapped under the work-lamp within 1–2 days. Most parcels reach you inside the week.",
    ),
    (
        "Wander the floor or pick up where you left off in the journal.",
        "Roam the floor or reopen the case file in the journal.",
    ),
    (
        "Long-form letters about new pieces, the makers behind them, and the materials we keep coming back to.",
        "Long-form letters about new pieces, the cutters behind them, and the cloth we keep coming back to.",
    ),
    (
        "Goods made to last a life. Raw materials, honest craft, and a thread count you can feel.",
        "Goods made to last a life. Raw materials, honest craft, and a thread count you can feel in the dark.",
    ),
    (
        "The page you came for has been mended, retired, or was never stitched. Try the search below or head back to the workshop.",
        "The page you came for slipped between filing cabinets, retired, or was never logged. Try the search below or head back to the bureau.",
    ),
    (
        "Notes from the bench on craft, commerce, and the goods we make.",
        "Notes from the desk on cloth, commerce, and the goods we move.",
    ),
    (
        "A standing letter from the bench.",
        "A standing letter from the night desk.",
    ),
    (
        "Wrapped in waxed paper, tied with twine. Felt like opening a parcel from another century.",
        "Wrapped in waxed paper, tied with butcher twine. Felt like opening evidence from another century.",
    ),
    (
        "Stitched like a garment built to outlast me. Already saving for the next one.",
        "Stitched like a coat built to outlast me. Already saving for the next one.",
    ),
    (
        "Take one home and wear it in.",
        "Take one home and let the street wear it in.",
    ),
    (
        "A new run, fresh off the bench.",
        "A new run, fresh off the night shift.",
    ),
    (
        "We pack at the bench within one business day and send tracking the moment it leaves.",
        "We pack under the green lamp within one business day and send tracking the moment it leaves.",
    ),
    (
        "A receipt is being couriered to your inbox. If it doesn't land, the spam folder is worth a look.",
        "A receipt is being wired to your inbox. If it doesn't land, the spam folder is worth a look.",
    ),
    (
        "Most cases close in 2–5 business days. Any loose ends? <a href=\"/contact/\">Send word to the bureau.</a>",
        "Most cases close in 2–5 business days. Any loose threads? <a href=\"/contact/\">Send word to the bureau.</a>",
    ),
    (
        "We\\'re still finishing the seams. Leave your email and we\\'ll send word the moment the workshop opens.",
        "We're still locking the last seam. Leave your email and we'll send word the moment the bureau opens.",
    ),
    (
        "What happens at the bench",
        "What happens at the bureau",
    ),
    ("More from the workshop", "More from the backroom"),
    ("Order on the bench", "Order on the ledger"),
    ("01 — On the bench", "01 — Inked on the ledger"),
    ("02 — Boxed at the bench", "02 — Wrapped in noir paper"),
    ("03 — On the road", "03 — Under streetlights"),
    ("Where it\\'s headed", "Where the courier heads"),
    ("Take what\\'s yours.", "Claim your dossier."),
    ("Made slow, sold honest.", "Cut slow, sold square."),
    (
        "A small workshop, two pairs of hands, and a stubborn belief that a good garment should outlive its first owner. Cut from noir denim, finished by people whose names we know.",
        "A small bureau, two pairs of hands, and a stubborn belief that a good garment should outlive its first owner. Cut from noir denim, finished by people whose names we know.",
    ),
    ("Nothing in the bag yet.", "Nothing clipped to the dolly yet."),
    ("Back to the shop floor", "Back to the selling floor"),
    ("Open the journal", "Open the dispatch log"),
    ("From the workbench", "From the dispatch desk"),
    ("How long until the parcel lands?", "How long until the crate lands?"),
    ("Do you ship past the border?", "Do you ship past the river?"),
    ("Can I follow the parcel?", "Can I follow the crate?"),
    ("How do I reach the workshop?", "How do I reach the bureau?"),
    ("From the visiting log", "From the guest ledger"),
    ("Shipping at no charge", "Carriage at no charge"),
    ("Made to outlast you", "Built to outlast you"),
    ("Shop the line", "Shop the dossier"),
    ("Shop the bench", "Shop the night floor"),
    ("Shop by trade", "Shop by bureau desk"),
    ("New off the bench", "New off the night shift"),
    ("Built for those who wear things out honestly.", "Built for those who wear things out honestly under streetlight."),
    (
        "No posts found in the journal yet.",
        "No posts filed in the journal yet.",
    ),
    ("From the Workbench", "From the Night Desk"),
    ("The Collection", "The Noir line"),
    ("New Off the Bench", "New Off the Night Shift"),
    ("Shop by Trade", "Shop by Bureau line"),
    ("Editor\\'s Selection · No. XIV", "Case file · No. XIV"),
    ("Off the line.", "Off the call sheet."),
    ("Browse the line", "Trace the inventory"),
    ("Back to the workshop", "Return to the bureau"),
    ("From the bench", "From the night desk"),
    ("Search the line", "Search the dossier"),
    ("Workshop ledger", "Bureau ledger"),
    ("The drawer was empty.", "The safe read empty."),
    (
        "Nothing came off the line. Try a different search or browse below.",
        "Nothing came off the wire. Try a different search or browse below.",
    ),
    ("Field notes from the workshop.", "Evidence from the dispatch room."),
    ("Read the journal →", "Open the night ledger →"),
    ("· All rights reserved.", "· Bureau reserves every line."),
    (
        "Complimentary shipping on orders over $100 · Ships in 3–5 days",
        "Carriage comped past $100 · Leaves the dock in 3–5 days",
    ),
    ("New season arrivals →", "Fresh cuts on the floor →"),
    ("Cutting fabric. Back soon.", "Cutting cloth. Back soon."),
    ("Take what's yours.", "Claim your dossier."),
    ("Where it's headed", "Where the courier heads"),
]


def main() -> int:
    pairs = sorted(PAIRS, key=lambda t: len(t[0]), reverse=True)
    for needle, repl in pairs:
        if needle in repl:
            raise SystemExit(f"cascade hazard: needle inside repl: {needle!r}")
    touched = 0
    subs = 0
    for sub in SCAN:
        base = NOIR / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in EXT:
                continue
            raw = path.read_text(encoding="utf-8")
            new = raw
            for needle, repl in pairs:
                if needle in new:
                    c = new.count(needle)
                    new = new.replace(needle, repl)
                    subs += c
            if new != raw:
                path.write_text(new, encoding="utf-8")
                touched += 1
                print(path.relative_to(ROOT).as_posix())
    print(f"apply_noir_voice: {subs} substitution(s) across {touched} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
