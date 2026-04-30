#!/usr/bin/env python3
"""Append WC override CSS chunks to every theme's top-level styles.css.

This script is a small append-only chain: each entry in CHUNKS is a
named CSS block bracketed by a unique `/* sentinel */ ... /* /sentinel */`
pair. On every run we walk CHUNKS in order, and for each chunk:

  * if its sentinel is already present in the theme's styles.css, skip;
  * otherwise splice it in just AFTER the previous chunk's closing
    sentinel (or, for the first chunk, after the canonical archive-page
    marker `/* /archive-product polish */` that already lives at the end
    of every theme's hand-authored CSS).

This means the script is idempotent (running it twice produces the same
file) and additive (a follow-up fix is just one more entry in CHUNKS;
the original chunk is left untouched).

The CSS uses tokens (`var(--wp--preset--color--*)`, `var(--wp--custom--*)`)
so the same chunk styles all four themes correctly with no per-theme
forking.

Why we splice raw text instead of round-tripping JSON: the existing
styles.css value is a single ~17 KB minified string per theme, containing
URL-encoded SVG and embedded double quotes (`\\"` in JSON). Round-tripping
through json.loads/json.dumps would re-encode every other string in the
file and produce massive irrelevant diffs.

Run from the theme repo root:
  python3 bin/append-wc-overrides.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def discover_themes(stages=None) -> list[str]:
    """Return every real theme slug on disk, in a stable order.

    A "real theme" is any top-level folder under the repo root that has
    BOTH `theme.json` and `playground/blueprint.json`. This is the same
    definition `bin/snap.py::discover_themes()` uses — we duplicate the
    filesystem walk here (instead of importing) so this script keeps
    its minimal top-of-file imports and stays runnable without pulling
    in the snap dependency graph.

    Why auto-discovery matters: the previous hardcoded list silently
    excluded Foundry (added after the list was written), which meant
    every cart/checkout/my-account WC chrome polish phase skipped
    Foundry and shipped a visibly broken theme to demo.regionallyfamous.
    Auto-discovery means "every theme ships every phase" is the default.

    Tier 1.3 readiness filter: ``stages`` is either None (use the
    default visible set = shipping only), an empty tuple / list (every
    stage including retired), or an explicit iterable of stage names.
    A theme without a readiness.json is treated as ``stage="shipping"``
    for backward compat. Incubating themes are hidden from the default
    WC-override append so a WIP theme's CSS chain doesn't become a
    tracked drift target before it's ready to ship.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _readiness import DEFAULT_VISIBLE_STAGES, load_readiness

    wanted: frozenset[str] | None
    if stages is None:
        wanted = DEFAULT_VISIBLE_STAGES
    else:
        s = frozenset(stages)
        wanted = s if s else None

    have: list[str] = []
    for p in sorted(ROOT.glob("*/theme.json")):
        if not (p.parent / "playground" / "blueprint.json").exists():
            continue
        if wanted is not None and load_readiness(p.parent).stage not in wanted:
            continue
        have.append(p.parent.name)
    have_set = set(have)
    # Historical order for the five original themes, for diff stability
    # (any new theme folder lands alphabetically after these).
    preferred = ["obel", "chonk", "selvedge", "lysholm", "aero"]
    ordered = [t for t in preferred if t in have_set]
    extras = [t for t in have if t not in preferred]
    return ordered + extras


THEMES = discover_themes()

SENTINEL_OPEN = "/* wc-tells: notices, meta, rating, variations, lightbox, mini-cart, cart, checkout, order-confirm, my-account */"
SENTINEL_CLOSE = "/* /wc-tells */"

# IMPORTANT: every value here uses tokens (`var(--wp--preset--*)`,
# `var(--wp--custom--*)`) so the same chunk is correct for all four themes.
# The chevron SVG is single-quoted internally so the outer `url("...")` can
# stay double-quoted (which is how the existing chevron rule in styles.css is
# written; the JSON encoder will escape the outer `"` to `\"` for us).
CSS = f"""{SENTINEL_OPEN}
.woocommerce-notices-wrapper{{margin-block:var(--wp--preset--spacing--lg);}}
.woocommerce-message,.woocommerce-error,.woocommerce-info{{border:0;border-radius:0;background:transparent;border-top:1px solid var(--wp--preset--color--border);border-bottom:1px solid var(--wp--preset--color--border);padding:var(--wp--preset--spacing--md) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--contrast);display:flex;align-items:center;justify-content:space-between;gap:var(--wp--preset--spacing--md);list-style:none;}}
.woocommerce-message::before,.woocommerce-error::before,.woocommerce-info::before{{display:none;content:none;}}
.woocommerce-error{{color:var(--wp--preset--color--error,var(--wp--preset--color--contrast));}}
.added_to_cart{{display:inline-flex;align-items:center;gap:var(--wp--preset--spacing--xs);background:transparent;color:var(--wp--preset--color--contrast);border:0;padding:0;text-decoration:none;font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;border-bottom:1px solid currentColor;}}
.added_to_cart:hover{{text-decoration:underline;text-decoration-color:var(--wp--preset--color--accent);text-decoration-thickness:2px;text-underline-offset:0.2em;}}
.product_meta .sku_wrapper>:first-child,.product_meta .posted_in>:first-child,.product_meta .tagged_as>:first-child{{display:none;}}
.product_meta .sku,.product_meta .posted_in a,.product_meta .tagged_as a{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--contrast);text-decoration:none;}}
.star-rating{{display:inline-block;position:relative;width:6rem;height:2px;overflow:hidden;background:var(--wp--preset--color--border);color:transparent;font-size:0;line-height:0;}}
.star-rating::before{{content:none;}}
.star-rating>span{{position:absolute;inset:0;right:auto;height:100%;background:var(--wp--preset--color--contrast);color:transparent;font-size:0;line-height:0;}}
.star-rating>span::before{{content:"";display:none;}}
.star-rating>span strong{{position:absolute;left:-9999px;}}
table.variations{{width:100%;border-collapse:collapse;margin:0 0 var(--wp--preset--spacing--md);}}
table.variations tr{{display:block;padding:var(--wp--preset--spacing--xs) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
table.variations th,table.variations td{{display:block;padding:0;border:0;text-align:left;}}
table.variations th{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin-bottom:var(--wp--preset--spacing--2-xs);}}
table.variations select{{appearance:none;-webkit-appearance:none;-moz-appearance:none;width:100%;background-color:var(--wp--preset--color--surface);background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8' fill='none'%3E%3Cpath d='M1 1.5L6 6.5L11 1.5' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right var(--wp--preset--spacing--sm) center;background-size:10px 6px;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);font:inherit;color:var(--wp--preset--color--contrast);padding:var(--wp--preset--spacing--sm) calc(var(--wp--preset--spacing--lg) + 12px) var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);}}
table.variations select:focus{{outline:none;border-color:var(--wp--preset--color--contrast);box-shadow:0 0 0 3px var(--wp--preset--color--accent-soft);}}
.reset_variations{{display:inline-block;margin-top:var(--wp--preset--spacing--sm);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);text-decoration:none;border-bottom:1px solid currentColor;}}
.reset_variations:hover{{color:var(--wp--preset--color--contrast);}}
.woocommerce-variation-price{{margin:var(--wp--preset--spacing--md) 0;}}
.woocommerce-variation-price .price{{font-size:var(--wp--preset--font-size--lg);color:var(--wp--preset--color--contrast);}}
.pswp__top-bar{{background:transparent;}}
.pswp__button{{color:var(--wp--preset--color--contrast);background:transparent;}}
.pswp__counter{{color:var(--wp--preset--color--secondary);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;}}
.flex-control-thumbs{{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--wp--preset--spacing--xs);margin:var(--wp--preset--spacing--md) 0 0;padding:0;list-style:none;}}
.flex-control-thumbs li{{margin:0;padding:0;}}
.flex-control-thumbs img{{display:block;width:100%;height:auto;border-radius:var(--wp--custom--radius--md);cursor:pointer;opacity:0.6;transition:opacity 160ms ease;}}
.flex-control-thumbs img:hover,.flex-control-thumbs img.flex-active{{opacity:1;}}
.wc-block-product-gallery-large-image-next-previous button{{background:transparent;border:1px solid var(--wp--preset--color--border);border-radius:9999px;color:var(--wp--preset--color--contrast);}}
.wc-block-product-gallery-large-image-next-previous button:hover{{border-color:var(--wp--preset--color--contrast);}}
.wc-block-mini-cart__drawer .components-modal__content{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--base);}}
.wc-block-mini-cart__title{{font-family:var(--wp--preset--font-family--display);font-weight:var(--wp--custom--font-weight--regular);font-size:var(--wp--preset--font-size--xl);letter-spacing:var(--wp--custom--letter-spacing--tight);}}
.wc-block-mini-cart-items{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);padding:0;margin:0;list-style:none;}}
.wc-block-mini-cart-items .wc-block-cart-item{{display:grid;grid-template-columns:64px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--sm) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-mini-cart-items .wc-block-cart-item img{{display:block;width:64px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-mini-cart__footer{{border-top:1px solid var(--wp--preset--color--border);padding-top:var(--wp--preset--spacing--md);margin-top:var(--wp--preset--spacing--md);}}
.wc-block-mini-cart__footer-actions{{display:grid;grid-template-columns:1fr 1fr;gap:var(--wp--preset--spacing--sm);}}
.wc-block-mini-cart__footer-actions a,.wc-block-mini-cart__footer-actions .wc-block-components-button{{display:inline-flex;align-items:center;justify-content:center;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);text-decoration:none;transition:background 160ms ease,color 160ms ease;}}
.wc-block-mini-cart__footer-actions a:hover,.wc-block-mini-cart__footer-actions .wc-block-components-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);}}
.wp-block-woocommerce-empty-mini-cart-contents-block{{text-align:center;font-family:var(--wp--preset--font-family--sans);}}
.wc-block-cart{{display:grid;grid-template-columns:1fr;gap:var(--wp--preset--spacing--2-xl);}}
@media (min-width:782px){{.wc-block-cart{{grid-template-columns:minmax(0,1fr) minmax(300px,360px);}}}}
.wc-block-cart-items,.wp-block-woocommerce-cart-line-items-block{{padding:0;margin:0;border-collapse:collapse;border:0;}}
.wc-block-cart-items th{{display:none;}}
.wc-block-cart-items .wc-block-cart-items__row{{display:grid;grid-template-columns:96px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--md) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-cart-item__image img{{display:block;width:96px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-cart-item__product .wc-block-components-product-name{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--md);font-weight:var(--wp--custom--font-weight--regular);color:var(--wp--preset--color--contrast);text-decoration:none;}}
.wc-block-cart-item__product .wc-block-components-product-name:hover{{text-decoration:underline;text-decoration-color:var(--wp--preset--color--accent);text-decoration-thickness:2px;text-underline-offset:0.2em;}}
.wc-block-cart-item__product .wc-block-components-product-metadata{{font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);margin-top:var(--wp--preset--spacing--2-xs);}}
.wc-block-cart-item__total{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);text-align:right;}}
.wc-block-components-quantity-selector{{display:inline-flex;align-items:stretch;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--pill);overflow:hidden;background:var(--wp--preset--color--surface);}}
.wc-block-components-quantity-selector__input{{width:48px;border:0;background:transparent;text-align:center;font-family:inherit;font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);appearance:textfield;-moz-appearance:textfield;}}
.wc-block-components-quantity-selector__input::-webkit-inner-spin-button,.wc-block-components-quantity-selector__input::-webkit-outer-spin-button{{-webkit-appearance:none;margin:0;}}
.wc-block-components-quantity-selector__button{{background:transparent;border:0;color:var(--wp--preset--color--contrast);width:32px;cursor:pointer;font-size:var(--wp--preset--font-size--base);transition:color 160ms ease;}}
.wc-block-components-quantity-selector__button:hover{{background:var(--wp--preset--color--accent-soft,var(--wp--preset--color--subtle,transparent));color:var(--wp--preset--color--contrast);}}
.wc-block-cart__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
.wc-block-components-totals-item{{display:flex;justify-content:space-between;align-items:baseline;padding:var(--wp--preset--spacing--xs) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.wc-block-components-totals-item__label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wc-block-components-totals-footer-item{{border-top:1px solid var(--wp--preset--color--border);padding-top:var(--wp--preset--spacing--md);margin-top:var(--wp--preset--spacing--xs);}}
.wc-block-components-totals-footer-item .wc-block-components-totals-item__value{{font-size:var(--wp--preset--font-size--lg);font-weight:var(--wp--custom--font-weight--medium);}}
.wc-block-components-totals-coupon__form{{display:flex;gap:var(--wp--preset--spacing--xs);}}
.wc-block-components-totals-coupon__input,.wc-block-components-totals-coupon input[type=text]{{flex:1;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
.wc-block-components-totals-coupon__button,.wc-block-components-totals-coupon button{{background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--lg);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;cursor:pointer;transition:background 160ms ease;}}
.wc-block-components-totals-coupon__button:hover,.wc-block-components-totals-coupon button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);}}
.wc-block-cart__submit-container .wc-block-components-checkout-place-order-button,.wc-block-cart__submit-container a.wc-block-cart__submit-button{{display:inline-flex;align-items:center;justify-content:center;width:100%;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wide);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--xl);text-decoration:none;cursor:pointer;transition:background 160ms ease,transform 160ms ease;}}
.wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover,.wc-block-cart__submit-container a.wc-block-cart__submit-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);transform:translateY(-1px);}}
.wc-block-cart-cross-sells{{margin-top:var(--wp--preset--spacing--3-xl);}}
.wc-block-cart-cross-sells>h2,.wc-block-cart-cross-sells .wp-block-heading{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--2-xl);margin:0 0 var(--wp--preset--spacing--lg);}}
.wc-block-components-shipping-calculator-address{{display:grid;gap:var(--wp--preset--spacing--sm);margin-top:var(--wp--preset--spacing--md);}}
.wc-block-checkout{{display:grid;grid-template-columns:1fr;gap:var(--wp--preset--spacing--2-xl);}}
@media (min-width:782px){{.wc-block-checkout{{grid-template-columns:minmax(0,1fr) minmax(300px,360px);}}}}
.wc-block-checkout__main{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xl);}}
.wc-block-components-checkout-step{{padding:var(--wp--preset--spacing--lg) 0;border-bottom:1px solid var(--wp--preset--color--border);position:relative;}}
.wc-block-components-checkout-step__heading{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--2-xs);margin-bottom:var(--wp--preset--spacing--md);}}
.wc-block-components-checkout-step__title{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--xl);font-weight:var(--wp--custom--font-weight--regular);color:var(--wp--preset--color--contrast);}}
.wc-block-components-checkout-step__description{{font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);}}
.wc-block-components-checkout-step__container::before{{display:none;content:none;}}
.wc-block-components-checkout-step__heading-content{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wc-block-checkout__login-prompt,.wc-block-checkout__contact-information .wc-block-components-checkout-step__heading-content a{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--contrast);text-decoration:none;border-bottom:1px solid currentColor;}}
.wc-block-checkout__login-prompt:hover,.wc-block-checkout__contact-information .wc-block-components-checkout-step__heading-content a:hover{{text-decoration:underline;text-decoration-color:var(--wp--preset--color--accent);text-decoration-thickness:2px;text-underline-offset:0.2em;}}
.wc-block-components-text-input input{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);transition:border-color 160ms ease,box-shadow 160ms ease;}}
.wc-block-components-text-input input:focus{{outline:none;border-color:var(--wp--preset--color--contrast);box-shadow:0 0 0 3px var(--wp--preset--color--accent-soft);}}
.wc-block-components-text-input label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wc-block-components-checkbox{{display:inline-flex;align-items:center;gap:var(--wp--preset--spacing--xs);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--secondary);}}
.wc-block-components-checkbox__input{{accent-color:var(--wp--preset--color--contrast);}}
.wc-block-components-payment-methods{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);}}
.wc-block-components-payment-method{{display:block;padding:var(--wp--preset--spacing--md);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);background:var(--wp--preset--color--surface);transition:border-color 160ms ease;}}
.wc-block-components-payment-method:hover{{border-color:var(--wp--preset--color--contrast);}}
.wc-block-components-payment-method label{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--medium);color:var(--wp--preset--color--contrast);}}
.wc-block-components-checkout-place-order-button{{display:inline-flex;align-items:center;justify-content:center;width:100%;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wide);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--xl);text-decoration:none;cursor:pointer;transition:background 160ms ease,transform 160ms ease;}}
.wc-block-components-checkout-place-order-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);transform:translateY(-1px);}}
.wc-block-components-order-summary{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);}}
.wc-block-components-order-summary-item{{display:grid;grid-template-columns:64px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--sm) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-components-order-summary-item__image img{{display:block;width:64px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-components-order-summary-item__description{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.wc-block-components-order-summary-item__quantity{{position:static;background:transparent;color:var(--wp--preset--color--secondary);font-size:var(--wp--preset--font-size--xs);width:auto;height:auto;border:0;}}
.wp-block-woocommerce-order-confirmation-downloads table{{width:100%;border-collapse:collapse;font-size:var(--wp--preset--font-size--sm);}}
.wp-block-woocommerce-order-confirmation-downloads th,.wp-block-woocommerce-order-confirmation-downloads td{{padding:var(--wp--preset--spacing--md);border-bottom:1px solid var(--wp--preset--color--border);text-align:left;vertical-align:top;}}
.wp-block-woocommerce-order-confirmation-downloads thead th{{background:var(--wp--preset--color--subtle);font-weight:var(--wp--custom--font-weight--semibold);text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider);font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);}}
.wp-block-woocommerce-order-confirmation-downloads .button{{display:inline-flex;align-items:center;justify-content:center;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--xs) var(--wp--preset--spacing--md);text-decoration:none;transition:background 160ms ease;}}
.wp-block-woocommerce-order-confirmation-downloads .button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);}}
.wp-block-woocommerce-order-confirmation-create-account form{{display:grid;gap:var(--wp--preset--spacing--md);padding:var(--wp--preset--spacing--lg);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);}}
.wp-block-woocommerce-order-confirmation-create-account label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wp-block-woocommerce-order-confirmation-create-account input[type=password],.wp-block-woocommerce-order-confirmation-create-account input[type=text]{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
.wp-block-woocommerce-order-confirmation-create-account input[type=submit],.wp-block-woocommerce-order-confirmation-create-account button[type=submit]{{background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--lg);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;cursor:pointer;}}
.woocommerce-account .woocommerce:has(>.woocommerce-MyAccount-navigation){{display:grid;grid-template-columns:220px 1fr;gap:var(--wp--preset--spacing--2-xl);}}
/* WC ships `.woocommerce::before, ::after {{content:" "; display:table}}` as a
   legacy clearfix. Once we flip `.woocommerce` to `display:grid`, those two
   pseudo-elements become GRID ITEMS (one per track), so grid auto-flow places
   ::before in cell (1,1), pushes the nav to (2,1), and wraps the content
   pane to row 2 at column 1 — the logged-in /my-account/ view renders with
   an empty column on the right and the dashboard cards collapsed into a
   narrow column underneath the nav. Neutralising the clearfix only inside
   the grid context preserves WC's default layout everywhere else. */
.woocommerce-account .woocommerce:has(>.woocommerce-MyAccount-navigation)::before,.woocommerce-account .woocommerce:has(>.woocommerce-MyAccount-navigation)::after{{display:none;content:none;}}
/* WC frontend.css also sets `.woocommerce-MyAccount-navigation
   {{float:left;width:30%}}` and `.woocommerce-MyAccount-content
   {{float:right;width:68%}}` for its legacy float-based two-col
   layout. Those percentage widths resolve against the GRID CELL
   when the parent becomes a grid, so the nav shrinks to 66px
   (30% of the 220px track) and the content to ~470px (68% of the
   692px track), leaving ~30% dead space inside each column. Reset
   width and float inside the grid context so each child fills its
   track. */
.woocommerce-account .woocommerce:has(>.woocommerce-MyAccount-navigation)>.woocommerce-MyAccount-navigation,.woocommerce-account .woocommerce:has(>.woocommerce-MyAccount-navigation)>.woocommerce-MyAccount-content{{width:auto;max-width:100%;float:none;}}
/* woocommerce-blocktheme.css caps `.woocommerce-account main .woocommerce`
   at `max-width:1000px` (WC wants a readable form column on account / cart
   / checkout surfaces). That cap is too narrow once the logged-in account
   wrapper becomes a two-column grid: nav + gap + dashboard cards need the
   full alignwide container or the content track overflows. */
.woocommerce-account .woocommerce:has(>.woocommerce-MyAccount-navigation){{width:100%;max-width:100%;margin-inline:auto;box-sizing:border-box;}}
.woocommerce-account .woocommerce:has(>.wo-account-login-grid),.woocommerce-account .woocommerce:has(>form.woocommerce-form-login){{display:block;max-width:100%;}}
.woocommerce-MyAccount-navigation ul{{list-style:none;padding:0;margin:0;display:grid;gap:0;}}
.woocommerce-MyAccount-navigation li{{margin:0;}}
.woocommerce-MyAccount-navigation a{{display:block;padding:var(--wp--preset--spacing--sm) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);text-decoration:none;border-bottom:1px solid var(--wp--preset--color--border);transition:color 160ms ease;}}
.woocommerce-MyAccount-navigation .is-active a,.woocommerce-MyAccount-navigation a:hover{{color:var(--wp--preset--color--contrast);}}
.woocommerce-MyAccount-content{{font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.woocommerce-MyAccount-content h2,.woocommerce-MyAccount-content h3{{font-family:var(--wp--preset--font-family--display);font-weight:var(--wp--custom--font-weight--regular);}}
.woocommerce-orders-table,.woocommerce-table--order-details,.shop_table{{width:100%;border-collapse:collapse;font-size:var(--wp--preset--font-size--sm);}}
.woocommerce-orders-table th,.woocommerce-orders-table td,.woocommerce-table--order-details th,.woocommerce-table--order-details td{{padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);border-bottom:1px solid var(--wp--preset--color--border);text-align:left;}}
.woocommerce-orders-table thead th,.woocommerce-table--order-details thead th{{background:var(--wp--preset--color--subtle);font-weight:var(--wp--custom--font-weight--semibold);text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider);font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);}}
.woocommerce-orders-table .button,.woocommerce-MyAccount-content .button{{display:inline-flex;align-items:center;justify-content:center;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--xs) var(--wp--preset--spacing--md);text-decoration:none;transition:background 160ms ease;}}
.woocommerce-MyAccount-content form .button:hover,.woocommerce-orders-table .button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);}}
.woocommerce-EditAccountForm,.woocommerce-address-fields__field-wrapper{{display:grid;gap:var(--wp--preset--spacing--md);}}
.woocommerce-EditAccountForm label,.woocommerce-address-fields__field-wrapper label{{display:block;font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin-bottom:var(--wp--preset--spacing--2-xs);}}
.woocommerce-EditAccountForm input,.woocommerce-address-fields__field-wrapper input,.woocommerce-EditAccountForm select,.woocommerce-address-fields__field-wrapper select{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
@media (max-width:720px){{.woocommerce-account .woocommerce:has(>.woocommerce-MyAccount-navigation){{grid-template-columns:1fr;}}}}
/* Branded dashboard (wo-account-*) — the markup is emitted by every
   theme's `// === BEGIN my-account ===` block in functions.php (see
   obel_render_account_dashboard() and its per-theme counterparts).
   Without CSS for these classes the dashboard paints as an unstyled
   bulleted list of headings, which was the second half of the
   "weird column thing" every theme inherited. */
.wo-account-dashboard{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xl);}}
.wo-account-greeting{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);margin:0;}}
.wo-account-greeting__eyebrow{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin:0;}}
.wo-account-greeting__title{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--3-xl);font-weight:var(--wp--custom--font-weight--regular);color:var(--wp--preset--color--contrast);margin:0;line-height:1.1;}}
.wo-account-greeting__lede{{font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--secondary);margin:0;max-width:56ch;}}
.wo-account-cards{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--wp--preset--spacing--lg);}}
@media (max-width:960px){{.wo-account-cards{{grid-template-columns:1fr;}}}}
.wo-account-card{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);padding:var(--wp--preset--spacing--lg);background:var(--wp--preset--color--surface,var(--wp--preset--color--subtle));border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);margin:0;transition:border-color 160ms ease;}}
.wo-account-card:hover{{border-color:var(--wp--preset--color--contrast);}}
.wo-account-card__eyebrow{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin:0;}}
.wo-account-card__title{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--xl);font-weight:var(--wp--custom--font-weight--regular);color:var(--wp--preset--color--contrast);margin:0;}}
.wo-account-card__lede{{font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--secondary);margin:0;flex:1;}}
.wo-account-card__cta{{display:inline-flex;align-items:center;gap:var(--wp--preset--spacing--2-xs);margin-top:var(--wp--preset--spacing--sm);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--contrast);text-decoration:none;border-bottom:1px solid var(--wp--preset--color--border);padding-bottom:var(--wp--preset--spacing--2-xs);align-self:flex-start;transition:border-color 160ms ease;}}
.wo-account-card__cta:hover{{border-bottom-color:var(--wp--preset--color--accent);border-bottom-width:2px;padding-bottom:calc(var(--wp--preset--spacing--2-xs) - 1px);}}
{SENTINEL_CLOSE}"""


# ---------------------------------------------------------------------------
# Follow-up chunk: cart page sidebar fix.
# ---------------------------------------------------------------------------
# The original group A (cart interior) used `grid-template-columns:2fr 1fr`
# at the 782px breakpoint. On tablet / narrow-desktop widths (~800-1000px)
# that shrinks the sidebar column to ~200px, which then squeezes the
# coupon disclosure into one-letter-per-line text and turns the
# Proceed-to-Checkout button into an oversized pill that overflows the
# card. The fix:
#   1. Clamp the sidebar to minmax(300px, 360px) so it always has usable
#      width and never grows beyond a comfortable reading column.
#   2. `min-width:0` on the grid children so they can shrink without
#      forcing the row to overflow horizontally.
#   3. Make the coupon disclosure an explicit flex row with the chevron
#      pinned to the right (was inline, with the chevron eating the row
#      width and forcing the label to wrap).
#   4. Tighten the submit button's padding + line-height so a two-word
#      label like "Proceed to Checkout" doesn't balloon into a tall pill.
# Same selectors target the WC Blocks cart on all four themes; tokens
# resolve per-theme.
SENTINEL_OPEN_CART_FIX = "/* wc-tells-cart-sidebar-fix */"
SENTINEL_CLOSE_CART_FIX = "/* /wc-tells-cart-sidebar-fix */"
CSS_CART_FIX = f"""{SENTINEL_OPEN_CART_FIX}
.wc-block-cart{{align-items:start;}}
@media (min-width:782px){{.wc-block-cart{{grid-template-columns:minmax(0,1fr) minmax(300px,360px);}}}}
.wc-block-cart__main,.wc-block-components-sidebar-layout__main,.wc-block-cart__sidebar,.wc-block-components-sidebar-layout__sidebar{{min-width:0;}}
.wc-block-cart__sidebar{{overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-cart__sidebar .wp-block-heading{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--xl);font-weight:var(--wp--custom--font-weight--regular);margin:0 0 var(--wp--preset--spacing--xs);overflow-wrap:break-word;}}
.wc-block-components-totals-coupon{{padding:0;}}
.wc-block-components-totals-coupon .wc-block-components-panel__button,.wc-block-components-panel>.wc-block-components-panel__button{{display:flex;align-items:center;justify-content:space-between;width:100%;gap:var(--wp--preset--spacing--xs);background:transparent;border:0;padding:var(--wp--preset--spacing--xs) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);cursor:pointer;text-align:left;white-space:normal;overflow-wrap:break-word;word-break:normal;}}
.wc-block-components-totals-coupon .wc-block-components-panel__button-icon,.wc-block-components-panel__button-icon{{flex:0 0 auto;width:14px;height:14px;}}
.wc-block-cart__submit-container{{margin-top:var(--wp--preset--spacing--sm);}}
.wc-block-cart__submit-container .wc-block-components-checkout-place-order-button,.wc-block-cart__submit-container a.wc-block-cart__submit-button{{padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;border-radius:var(--wp--custom--radius--pill);overflow-wrap:break-word;word-break:normal;line-height:1.2;min-width:0;}}
{SENTINEL_CLOSE_CART_FIX}"""


# ---------------------------------------------------------------------------
# Follow-up chunk: checkout order-summary sidebar fix.
# ---------------------------------------------------------------------------
# The original group B (checkout interior) hit the same squeeze as the
# cart, only worse: the right column on checkout hosts the
# `.wc-block-components-order-summary-item`, which is itself a nested
# 3-column grid (64px image / 1fr description / auto price). Without
# `min-width:0` on the description and price grid children, intrinsic
# content size forces row overflow — at sidebar widths around 80-150px
# the product name wraps to one glyph per line ("A / r / t / i / s / a /
# n / a / l").
#
# The fix mirrors the cart chunk and adds two new pieces:
#   1. `.wc-block-checkout` sidebar clamp + `min-width:0` on every grid
#      child (parent and order-summary children).
#   2. `min-width:0` + `overflow-wrap:break-word; word-break:normal` on
#      the description / total / individual-prices columns inside each
#      order-summary item, so long product names wrap on word boundaries.
#   3. The same on `.wc-block-cart-item__product` / `__total` for parity
#      (the cart line items don't suffer the same way today because they
#      live in the main column, but a future redesign that moves them
#      into a sidebar would re-trigger the bug).
#
# bin/check.py grows a `check_no_squeezed_wc_sidebars` companion rule
# that asserts each of the three sidebar selectors carries
# `min-width:0`, forbids `word-break:break-all` anywhere, and forbids
# the original `2fr 1fr` grid for either parent. That rule is the
# guardrail that makes the regression undeployable.
SENTINEL_OPEN_CO_FIX = "/* wc-tells-checkout-summary-fix */"
SENTINEL_CLOSE_CO_FIX = "/* /wc-tells-checkout-summary-fix */"
CSS_CO_FIX = f"""{SENTINEL_OPEN_CO_FIX}
.wc-block-checkout{{align-items:start;}}
@media (min-width:782px){{.wc-block-checkout{{grid-template-columns:minmax(0,1fr) minmax(300px,360px);}}}}
.wc-block-checkout__main,.wc-block-checkout__sidebar,.wc-block-components-sidebar-layout__sidebar,.wc-block-components-sidebar-layout__main{{min-width:0;}}
.wc-block-checkout__sidebar{{overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-checkout__sidebar .wp-block-heading{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--xl);font-weight:var(--wp--custom--font-weight--regular);overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-components-order-summary-item{{grid-template-columns:48px minmax(0,1fr) auto;align-items:start;gap:var(--wp--preset--spacing--sm);}}
.wc-block-components-order-summary-item__image{{flex:0 0 auto;width:48px;}}
.wc-block-components-order-summary-item__image img{{width:48px;height:auto;}}
.wc-block-components-order-summary-item__description,.wc-block-components-order-summary-item__total,.wc-block-components-order-summary-item__individual-prices{{min-width:0;overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-components-order-summary-item__total{{text-align:right;font-variant-numeric:tabular-nums;}}
.wc-block-components-product-name{{display:block;overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-components-product-price{{overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-components-product-price ins,.wc-block-components-product-price del{{display:inline-block;}}
.wc-block-components-formatted-money-amount{{white-space:nowrap;}}
.wc-block-cart-item__product,.wc-block-cart-item__total{{min-width:0;overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-components-product-metadata{{overflow-wrap:break-word;word-break:normal;}}
{SENTINEL_CLOSE_CO_FIX}"""


# ---------------------------------------------------------------------------
# Follow-up chunk: grid-cell fill fix for cart + checkout sidebar layout.
# ---------------------------------------------------------------------------
# Diagnosed via bin/snap.py and a Playwright getMatchedCSSRules probe
# (Apr 2026). WC ships these legacy float-era rules in blocks/cart.css:
#
#   .wc-block-components-main    { width: 65%; padding-right: 4.5283%;  }
#   .wc-block-components-sidebar { width: 35%; padding-left: 2.26415%;  }
#
# Their own width:100% override is wrapped in
#   @container (max-width: 699px)
# which only fires when the .wp-block-woocommerce-cart container query
# host (set to container-type: inline-size) is below 700px. On a 1280px
# desktop our container is 1200px wide, the @container rule does NOT
# fire, and the legacy 35%/65% widths leak through. Because the
# .wc-block-cart parent is `display:grid` with template-columns
# `minmax(0,1fr) minmax(300px,360px)`, the children get sized as
# percentages of THEIR GRID CELL widths -- 35% of 360px = 126px sidebar
# and 65% of 752px = 489px main column. The visual symptom: the cart
# sidebar collapses to ~126px (showing "CAR T TOT ALS" wrapping per
# letter) and the main column squeezes line items into ~489px even
# though the page reserves 1200px for the cart.
#
# Fix: bump specificity above WC's (.wc-block-components-sidebar-layout
# .wc-block-components-main, 0,2,0) by combining the layout host class
# with the cart/checkout host class (0,3,0), then force width:100% so
# grid items fill their cells.
#
# This fix is applied to BOTH cart and checkout because they share the
# .wc-block-components-sidebar-layout shell, the same WC blocks/cart.css
# rules apply to both, and the regression manifests identically on
# /cart and /checkout. Discovered originally on /checkout/?demo=cart.
#
# IMPORTANT - do NOT add `padding-left:0; padding-right:0` here.
# The previous version of this chunk zeroed horizontal padding on
# `.wc-block-components-sidebar-layout.wc-block-cart > .wc-block-
# components-sidebar` (specificity 0,3,0) to "zero out WC's companion
# percentage paddings". The footgun: that selector matches the SAME
# DOM node that carries `.wc-block-cart__sidebar` AND
# `.wp-block-woocommerce-cart-totals-block` — i.e. the painted card
# surface. Phase G's `body.theme-X .wc-block-cart__sidebar { padding:
# xl }` is only specificity (0,2,0); GRID_FIX at (0,3,0) won the
# cascade and silently deleted the card's left/right padding, so
# every theme rendered "Order summary" + line items flush at the
# panel's left edge. Phase H + `check_wc_totals_blocks_padded` cover
# the totals selector specifically; this comment is the load-bearing
# reminder for the SIDEBAR wrapper. If WC's legacy percentage
# paddings ever leak back, fix them with a more targeted rule that
# does NOT also match the painted-card class — e.g. scope by direct
# child of `.wc-block-components-sidebar-layout` ONLY when the child
# is the unpainted `.wc-block-components-main`, not the painted
# `.wc-block-components-sidebar`.
SENTINEL_OPEN_GRID_FIX = "/* wc-tells-grid-cell-fill */"
SENTINEL_CLOSE_GRID_FIX = "/* /wc-tells-grid-cell-fill */"
# CSS_GRID_FIX has two parts:
#
# 1. Force the cart/checkout sidebar-layout grid CHILDREN to fill their
#    cells (overrides WC's legacy 35%/65% width rules in blocks/cart.css).
#
# 2. Un-grid the OUTER checkout wrapper. WC's checkout markup is a
#    `<div class="wp-block-woocommerce-checkout wc-block-checkout">`
#    that contains a SECOND `<div class="wc-block-components-sidebar-
#    layout wc-block-checkout">` — both elements match `.wc-block-
#    checkout` so our base grid rule (display:grid;
#    grid-template-columns:1fr 360px) hits twice. The outer steals 360px
#    for a phantom sidebar, leaving the real inner sidebar-layout only
#    752px to split between main + 360px sidebar (= 304px main, the
#    "checkout main is 304px" regression). Resetting the outer to a
#    block layout lets the inner grid use the full 1200px (~840 main +
#    360 sidebar). Cart is unaffected because its outer wrapper
#    (`wp-block-woocommerce-cart`) does not carry `.wc-block-cart`.
SENTINEL_OPEN_CO_OUTER = "/* wc-tells-checkout-outer-unwrap */"
SENTINEL_CLOSE_CO_OUTER = "/* /wc-tells-checkout-outer-unwrap */"
CSS_CO_OUTER = f"""{SENTINEL_OPEN_CO_OUTER}
.wp-block-woocommerce-checkout.wc-block-checkout{{display:block;grid-template-columns:none;gap:0;}}
{SENTINEL_CLOSE_CO_OUTER}"""
CSS_GRID_FIX = f"""{SENTINEL_OPEN_GRID_FIX}
.wc-block-components-sidebar-layout.wc-block-cart>.wc-block-components-main,.wc-block-components-sidebar-layout.wc-block-cart>.wc-block-components-sidebar,.wc-block-components-sidebar-layout.wc-block-checkout>.wc-block-components-main,.wc-block-components-sidebar-layout.wc-block-checkout>.wc-block-components-sidebar{{width:100%;}}
{SENTINEL_CLOSE_GRID_FIX}"""


# ---------------------------------------------------------------------------
# Follow-up chunk: Phase A premium fixes.
# ---------------------------------------------------------------------------
# Six small CSS guards that kill the "looks broken" tells observed across
# all 4 themes' visual baselines:
#
#   1. PDP featured image. Switching the single-product template from the
#      legacy `wp:woocommerce/product-image-gallery` (Flexslider/PhotoSwipe
#      JS-dependent, opacity:0 until JS init) to `wp:post-featured-image`
#      gives us a clean static <img>. We add a `wp-block-post-featured-
#      image` CSS rule to enforce a square-ish aspect-ratio, fluid width,
#      and a soft surface bg so the image always looks intentional.
#   2. Force any leftover legacy `.woocommerce-product-gallery` instances
#      visible regardless of WC frontend JS state (defensive: catches
#      product blocks rendered via shortcode or 3rd-party widgets).
#   3. Variation <select> font fallback. Chonk's display font (Marvin
#      Visions) lacks coverage for "Choose an option" / variant labels,
#      which is why the size/finish dropdowns rendered as a single em-dash
#      glyph in the desktop screenshot. Pin variation selects to the
#      sans-serif preset so the option text always renders.
#   4. Loading-skeleton ground-truth (moved). The original Phase A
#      shipped a `display:none!important` blanket on
#      `.wc-block-components-skeleton{,__element}` and
#      `.wc-block-components-loading-mask`. Rationale at the time was
#      "real content replaces it ~50ms later anyway", which held for
#      warm dev runs but failed on first-load and on slow XHR rounds:
#      the cart/checkout pages flashed a blank wide column for the
#      ~300-800ms WC Blocks needs to hydrate the cart store, which
#      reads to shoppers as a broken layout. The skeleton is the
#      *correct* loading affordance — we just want it painted in each
#      theme's tokens instead of WC's default neutral grey. The
#      paint chunk ships separately as Phase N (`wc-tells-phase-n-
#      skeleton`); Phase A no longer touches the skeleton at all.
#   5. Cart line items: enforce flex-column layout on `.wc-block-cart-
#      items` and grid-card layout on each row, so even if WC ever serves
#      the legacy <table> markup our CSS reframes it as a card list.
#   6. Hide WC's "Uncategorized" breadcrumb segment so PDPs don't read
#      as accidentally-uncategorised. Done as a CSS rule that targets
#      breadcrumb anchors whose href ends with `/uncategorized/`.
SENTINEL_OPEN_PHASE_A = "/* wc-tells-phase-a-premium */"
SENTINEL_CLOSE_PHASE_A = "/* /wc-tells-phase-a-premium */"
CSS_PHASE_A = f"""{SENTINEL_OPEN_PHASE_A}
.wp-block-woocommerce-single-product .wp-block-post-featured-image,.single-product .wp-block-post-featured-image{{margin:0;background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);overflow:hidden;}}
.wp-block-woocommerce-single-product .wp-block-post-featured-image img,.single-product .wp-block-post-featured-image img{{display:block;width:100%;height:auto;aspect-ratio:1/1;object-fit:cover;}}
.woocommerce-product-gallery{{opacity:1!important;}}
.woocommerce-product-gallery__image>a,.woocommerce-product-gallery__image>a>img{{display:block;width:100%;}}
.woocommerce-product-gallery__image img.wp-post-image{{display:block!important;width:100%!important;height:auto!important;opacity:1!important;}}
table.variations select,select.wo-variation{{font-family:var(--wp--preset--font-family--sans)!important;font-size:var(--wp--preset--font-size--sm)!important;}}
.wc-block-cart-items{{display:flex;flex-direction:column;}}
.wc-block-cart-items>tbody{{display:contents;}}
.wc-block-cart-items__row{{display:grid;grid-template-columns:96px minmax(0,1fr) auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--md) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.woocommerce-breadcrumb a[href$="/uncategorized/"],.wc-block-components-breadcrumbs a[href$="/uncategorized/"]{{display:none;}}
.woocommerce-breadcrumb a[href$="/uncategorized/"]+span,.wc-block-components-breadcrumbs a[href$="/uncategorized/"]+span{{display:none;}}
{SENTINEL_CLOSE_PHASE_A}"""


# ---------------------------------------------------------------------------
# Follow-up chunk: Phase B microcopy support classes.
# ---------------------------------------------------------------------------
# The wo-microcopy-mu.php mu-plugin (installed by every blueprint) emits
# two custom classes that need light styling so the swapped strings look
# intentional rather than naked DOM:
#
#   .wo-required-mark   — replaces WC's red `<abbr class="required">*`
#                         with a single secondary-colored mid-dot. We
#                         render at line-height:1 so it never lifts the
#                         label baseline.
#
# A second class, `.wo-result-count`, used to live in this chunk —
# pinned typography on the `<p class="woocommerce-result-count
# wo-result-count">N items</p>` element the mu-plugin emitted via a
# `woocommerce_before_shop_loop` action. That action fires INSIDE
# `wp:woocommerce/product-collection`'s server render too, so the count
# appeared TWICE on every archive: once in the title flex row
# (block-rendered, correct position) and once floating above the grid
# with no parent container. The mu-plugin now uses a
# `render_block_woocommerce/product-results-count` filter that rewrites
# the existing block <p> in place (see the comment block above that
# filter in `playground/wo-microcopy-mu.php` for the post-mortem). The
# rendered <p> only carries `woocommerce-result-count`, so the
# `.wo-result-count` selector matched nothing at runtime — we stripped
# it from every shipped `theme.json` in the same commit that retired
# the action, and we keep the sentinel name stable so an in-place
# strip is enough (no chunk re-append needed). Per-theme typography
# for the count lives in each `theme.json`'s
# `styles.blocks["woocommerce/product-results-count"]` entry.
SENTINEL_OPEN_PHASE_B = "/* wc-tells-phase-b-microcopy */"
SENTINEL_CLOSE_PHASE_B = "/* /wc-tells-phase-b-microcopy */"
CSS_PHASE_B = f"""{SENTINEL_OPEN_PHASE_B}
.wo-required-mark{{display:inline-block;margin-left:var(--wp--preset--spacing--2-xs);color:var(--wp--preset--color--secondary);font-weight:var(--wp--custom--font-weight--regular);line-height:1;}}
{SENTINEL_CLOSE_PHASE_B}"""


# ---------------------------------------------------------------------------
# Phase C: Premium PDP, archive, mini-cart, order-summary, payment icons.
# ---------------------------------------------------------------------------
# Single CSS chunk that delivers the visual half of Phase C across every
# theme. Each block below is grouped by feature area so future tweaks can
# find the relevant rules without re-reading the whole chunk.
#
#   1. Swatches             — replaces native variation <select> with a
#                             button group of color/size pills. Hidden
#                             select still drives WC's variation_form JS.
#   2. Sticky PDP gallery   — pins the featured image at desktop while
#                             the summary column scrolls. No-op on mobile.
#   3. Hover-reveal ATC     — shop archive cards keep ATC hidden until
#                             hover/keyboard focus. Always visible at
#                             touch breakpoint (no hover state).
#   4. Mini-cart drawer     — branded header, card line items, sticky
#                             footer with proper spacing for totals + CTA.
#   5. Order-summary brand  — 64x64 rounded thumbs, tabular-nums totals,
#                             logo-mark heading, accepted-payments strip.
#   6. Quantity selector    — drops the spinner-default look in favor of
#                             a typography-driven [-  3  +] tri-cell.
#   7. Payment-icons strip  — styles the .wo-payment-icons container that
#                             each theme's `// === BEGIN payment-icons ===`
#                             block in `<theme>/functions.php` injects via
#                             `wp_footer` below the Place Order button on
#                             cart + checkout (migrated from the deleted
#                             `playground/wo-payment-icons-mu.php`).
SENTINEL_OPEN_PHASE_C = "/* wc-tells-phase-c-premium */"
SENTINEL_CLOSE_PHASE_C = "/* /wc-tells-phase-c-premium */"
CSS_PHASE_C = f"""{SENTINEL_OPEN_PHASE_C}
.wo-swatch-wrap{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);}}
.wo-swatch-select{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}}
.wo-swatch-group{{display:flex;flex-wrap:wrap;gap:var(--wp--preset--spacing--xs);align-items:center;}}
.wo-swatch{{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:0 var(--wp--preset--spacing--sm);border:1px solid var(--wp--preset--color--border);background:transparent;color:var(--wp--preset--color--contrast);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--regular);letter-spacing:var(--wp--custom--letter-spacing--wide);text-transform:uppercase;cursor:pointer;transition:border-color 160ms ease,color 160ms ease,background 160ms ease;border-radius:var(--wp--custom--radius--sm,4px);}}
.wo-swatch:hover{{border-color:var(--wp--preset--color--contrast);}}
.wo-swatch:focus-visible{{outline:2px solid var(--wp--preset--color--accent);outline-offset:2px;}}
.wo-swatch.is-selected{{border-color:var(--wp--preset--color--contrast);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);}}
.wo-swatch--color{{width:40px;min-width:40px;padding:0;border-radius:50%;}}
.wo-swatch--color .wo-swatch__dot{{display:block;width:28px;height:28px;border-radius:50%;background:var(--wo-swatch-color,var(--wp--preset--color--border));box-shadow:inset 0 0 0 1px rgba(0,0,0,0.08);}}
.wo-swatch--color.is-selected{{background:transparent;color:inherit;outline:2px solid var(--wp--preset--color--contrast);outline-offset:2px;}}
table.variations td.label{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);padding-right:var(--wp--preset--spacing--md);vertical-align:middle;}}
.reset_variations{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
@media (min-width:1024px){{.single-product .wp-block-woocommerce-single-product>.wp-block-columns>.wp-block-column:first-child .wp-block-post-featured-image,.single-product .wp-block-columns>.wp-block-column:first-child .wp-block-post-featured-image{{position:sticky;top:var(--wp--preset--spacing--xl,24px);align-self:flex-start;}}}}
.wp-block-product-template .wp-block-product .wp-block-button.wc-block-components-product-button,.wp-block-product-template .wp-block-product .wp-block-add-to-cart-button{{opacity:0;transform:translateY(4px);transition:opacity 200ms ease,transform 200ms ease;}}
.wp-block-product-template .wp-block-product:hover .wp-block-button.wc-block-components-product-button,.wp-block-product-template .wp-block-product:focus-within .wp-block-button.wc-block-components-product-button,.wp-block-product-template .wp-block-product:hover .wp-block-add-to-cart-button,.wp-block-product-template .wp-block-product:focus-within .wp-block-add-to-cart-button{{opacity:1;transform:translateY(0);}}
@media (hover:none){{.wp-block-product-template .wp-block-product .wp-block-button.wc-block-components-product-button,.wp-block-product-template .wp-block-product .wp-block-add-to-cart-button{{opacity:1;transform:none;}}}}
.wc-block-mini-cart__drawer .wc-block-components-drawer__content,.wc-block-mini-cart__drawer{{background:var(--wp--preset--color--base);}}
.wc-block-mini-cart__drawer .wc-block-mini-cart__title{{font-family:var(--wp--preset--font-family--display,var(--wp--preset--font-family--serif));font-size:var(--wp--preset--font-size--lg);letter-spacing:var(--wp--custom--letter-spacing--tight);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--lg);border-bottom:1px solid var(--wp--preset--color--border);margin:0;}}
.wc-block-mini-cart__drawer .wc-block-mini-cart__items{{padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--lg);}}
.wc-block-mini-cart__drawer .wc-block-mini-cart__footer{{position:sticky;bottom:0;background:var(--wp--preset--color--base);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--lg);border-top:1px solid var(--wp--preset--color--border);box-shadow:0 -8px 24px rgba(0,0,0,0.04);}}
.wc-block-mini-cart__drawer .wc-block-cart-item__image img,.wc-block-cart-items img{{width:64px!important;height:64px!important;object-fit:cover;border-radius:var(--wp--custom--radius--sm,4px);background:var(--wp--preset--color--subtle);}}
.wc-block-components-totals-item__value,.wc-block-components-formatted-money-amount,.woocommerce-Price-amount,.amount{{font-variant-numeric:tabular-nums;}}
.wc-block-components-order-summary__button-text,.wc-block-cart-item__product-name,.wc-block-components-product-name{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--regular);}}
.wc-block-components-totals-item--total .wc-block-components-totals-item__label,.wc-block-components-totals-footer-item .wc-block-components-totals-item__label{{font-family:var(--wp--preset--font-family--display,var(--wp--preset--font-family--serif));font-size:var(--wp--preset--font-size--md);letter-spacing:var(--wp--custom--letter-spacing--tight);text-transform:none;}}
.wp-block-woocommerce-cart-totals-block::before{{content:"Order summary";display:block;font-family:var(--wp--preset--font-family--display,var(--wp--preset--font-family--serif));font-size:var(--wp--preset--font-size--lg);letter-spacing:var(--wp--custom--letter-spacing--tight);margin:0 0 var(--wp--preset--spacing--md);padding-bottom:var(--wp--preset--spacing--sm);border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-components-checkout-order-summary__title .wc-block-components-checkout-order-summary__title-text{{font-family:var(--wp--preset--font-family--display,var(--wp--preset--font-family--serif));font-size:var(--wp--preset--font-size--lg);letter-spacing:var(--wp--custom--letter-spacing--tight);font-weight:var(--wp--custom--font-weight--regular,400);margin:0 0 var(--wp--preset--spacing--md);padding-bottom:var(--wp--preset--spacing--sm);border-bottom:1px solid var(--wp--preset--color--border);text-transform:none;color:inherit;}}
.quantity input[type="number"].qty{{width:64px;height:44px;padding:0 var(--wp--preset--spacing--xs);text-align:center;font-family:var(--wp--preset--font-family--sans);font-variant-numeric:tabular-nums;font-size:var(--wp--preset--font-size--md);border:1px solid var(--wp--preset--color--border);background:transparent;-moz-appearance:textfield;}}
.quantity input[type="number"].qty::-webkit-outer-spin-button,.quantity input[type="number"].qty::-webkit-inner-spin-button{{-webkit-appearance:none;margin:0;}}
.quantity{{display:inline-flex;align-items:center;gap:0;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--sm,4px);overflow:hidden;}}
.quantity input[type="number"].qty{{border:none;}}
.wc-block-components-quantity-selector{{font-variant-numeric:tabular-nums;}}
.wo-payment-icons{{display:flex;flex-wrap:wrap;align-items:center;gap:var(--wp--preset--spacing--sm);justify-content:flex-start;margin:var(--wp--preset--spacing--md) 0 0;padding:var(--wp--preset--spacing--md) 0 0;border-top:1px solid var(--wp--preset--color--border);}}
.wo-payment-icons__label{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin-right:var(--wp--preset--spacing--xs);}}
.wo-payment-icons__list{{display:inline-flex;flex-wrap:wrap;gap:var(--wp--preset--spacing--xs);align-items:center;}}
.wo-payment-icons__icon{{display:inline-flex;align-items:center;justify-content:center;height:26px;width:40px;padding:0;border:0;border-radius:4px;background:transparent;overflow:hidden;line-height:0;}}
.wo-payment-icons__icon>svg{{display:block;width:100%;height:100%;}}
{SENTINEL_CLOSE_PHASE_C}"""


# ---------------------------------------------------------------------------
# Phase D: Branded WC pages — account, empty states, archive header,
# order-confirmation polish.
# ---------------------------------------------------------------------------
# Pairs with the page-level injections in each theme's
# `// === BEGIN my-account / empty-states / archive-hero ===` blocks
# (migrated from the deleted `playground/wo-pages-mu.php`) and the
# templates in <theme>/templates/{order-confirmation,404}.html. Each
# block here is keyed to a CSS class produced by the per-theme callback
# or the template, never relies on WC core selectors that might change
# shape.
#
#   1. wo-account-intro / wo-account-help — branded login intro panel
#      and trailing help text injected around the WC login form.
#   2. wo-empty / wo-empty__* — generic branded empty state used by
#      cart, shop archives, search results, 404, and order-not-found.
#   3. wo-archive-hero — editorial hero strip injected before the
#      product archive loop. Has cover-image variant when the term has
#      a thumbnail, falls back to text-only otherwise.
#   4. wo-next-steps / wo-recs — order-confirmation supplementary
#      sections (3-step "what happens next", 4-card recs grid).
SENTINEL_OPEN_PHASE_D = "/* wc-tells-phase-d-pages */"
SENTINEL_CLOSE_PHASE_D = "/* /wc-tells-phase-d-pages */"
CSS_PHASE_D = f"""{SENTINEL_OPEN_PHASE_D}
.woocommerce-account .woocommerce>.u-columns,.woocommerce-account .u-columns{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--wp--preset--spacing--2-xl);align-items:start;}}
@media (max-width:768px){{.woocommerce-account .woocommerce>.u-columns,.woocommerce-account .u-columns{{grid-template-columns:1fr;}}}}
.wo-account-intro{{padding:var(--wp--preset--spacing--xl) 0;border-right:1px solid var(--wp--preset--color--border);padding-right:var(--wp--preset--spacing--xl);}}
@media (max-width:768px){{.wo-account-intro{{border-right:0;padding-right:0;border-bottom:1px solid var(--wp--preset--color--border);padding-bottom:var(--wp--preset--spacing--lg);}}}}
.wo-account-intro__eyebrow{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin:0 0 var(--wp--preset--spacing--xs);}}
.wo-account-intro__title{{font-family:var(--wp--preset--font-family--display,var(--wp--preset--font-family--serif));font-size:var(--wp--preset--font-size--3-xl);letter-spacing:var(--wp--custom--letter-spacing--tight);line-height:1.05;margin:0 0 var(--wp--preset--spacing--md);}}
.wo-account-intro__lede{{color:var(--wp--preset--color--secondary);margin:0 0 var(--wp--preset--spacing--md);}}
.wo-account-intro__perks{{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);}}
.wo-account-intro__perks li{{position:relative;padding-left:var(--wp--preset--spacing--md);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.wo-account-intro__perks li::before{{content:"";position:absolute;left:0;top:0.65em;width:6px;height:6px;background:var(--wp--preset--color--accent);border-radius:50%;}}
.wo-account-help{{margin-top:var(--wp--preset--spacing--lg);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--secondary);}}
.wo-empty{{display:flex;flex-direction:column;align-items:center;text-align:center;gap:var(--wp--preset--spacing--md);padding:var(--wp--preset--spacing--3-xl) 0;}}
.wo-empty__art{{width:120px;height:auto;color:var(--wp--preset--color--secondary);}}
.wo-empty__eyebrow{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin:0;}}
.wo-empty__title{{font-family:var(--wp--preset--font-family--display,var(--wp--preset--font-family--serif));font-size:var(--wp--preset--font-size--4-xl);letter-spacing:var(--wp--custom--letter-spacing--tight);line-height:1.05;margin:0;}}
.wo-empty__lede{{max-width:48ch;color:var(--wp--preset--color--secondary);margin:0;}}
.wo-empty__ctas{{display:inline-flex;flex-wrap:wrap;gap:var(--wp--preset--spacing--sm);justify-content:center;margin:var(--wp--preset--spacing--md) 0 0;}}
.wo-empty__cta{{display:inline-flex;align-items:center;justify-content:center;height:48px;padding:0 var(--wp--preset--spacing--lg);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);letter-spacing:var(--wp--custom--letter-spacing--wide);text-transform:uppercase;text-decoration:none;border-radius:var(--wp--custom--radius--sm,4px);transition:background 160ms ease,color 160ms ease,border-color 160ms ease;}}
.wo-empty__cta--primary{{background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);}}
.wo-empty__cta--primary:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);}}
.wo-empty__cta--secondary{{background:transparent;color:var(--wp--preset--color--contrast);border:1px solid var(--wp--preset--color--border);}}
.wo-empty__cta--secondary:hover{{border-color:var(--wp--preset--color--contrast);}}
.wo-archive-hero{{position:relative;padding:var(--wp--preset--spacing--3-xl) var(--wp--preset--spacing--lg);text-align:center;background:var(--wp--preset--color--subtle);background-size:cover;background-position:center;margin-bottom:var(--wp--preset--spacing--2-xl);}}
.wo-archive-hero--has-cover{{min-height:300px;display:flex;align-items:center;justify-content:center;color:var(--wp--preset--color--base);}}
.wo-archive-hero--has-cover::before{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0.25) 0%,rgba(0,0,0,0.55) 100%);}}
.wo-archive-hero__inner{{position:relative;display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);max-width:680px;margin:0 auto;}}
.wo-archive-hero__eyebrow{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;opacity:0.9;margin:0;}}
.wo-archive-hero__title{{font-family:var(--wp--preset--font-family--display,var(--wp--preset--font-family--serif));font-size:var(--wp--preset--font-size--5-xl);letter-spacing:var(--wp--custom--letter-spacing--tight);line-height:1;margin:0;}}
.wo-archive-hero__lede{{font-size:var(--wp--preset--font-size--md);max-width:48ch;margin:var(--wp--preset--spacing--xs) auto 0;opacity:0.85;}}
.wo-archive-hero__lede p{{margin:0;}}
.wo-next-steps .wp-block-paragraph,.wo-next-steps p{{font-size:var(--wp--preset--font-size--sm);}}
.wo-recs .wp-block-product-template,.wo-recs .wp-block-product-collection .wp-block-post-template{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--wp--preset--spacing--lg);}}
@media (max-width:900px){{.wo-recs .wp-block-product-template,.wo-recs .wp-block-product-collection .wp-block-post-template{{grid-template-columns:repeat(2,minmax(0,1fr));}}}}
{SENTINEL_CLOSE_PHASE_D}"""


# ---------------------------------------------------------------------------
# Phase D follow-up: per-theme distinctive footer CSS.
# ---------------------------------------------------------------------------
# Footer wordmark + newsletter signup styles. Selectors are scoped to
# the per-theme footer classes so dropping them into the shared chunk
# only renders in the theme that actually emits those classes.
SENTINEL_OPEN_PHASE_D_FOOTER = "/* wc-tells-phase-d-footer */"
SENTINEL_CLOSE_PHASE_D_FOOTER = "/* /wc-tells-phase-d-footer */"
CSS_PHASE_D_FOOTER = f"""{SENTINEL_OPEN_PHASE_D_FOOTER}
.chonk-footer__wordmark .wp-block-site-title a{{color:var(--wp--preset--color--contrast);text-decoration:none;display:block;}}
.chonk-footer__wordmark .wp-block-site-title a:hover{{text-decoration:underline;text-decoration-color:var(--wp--preset--color--accent);text-decoration-thickness:2px;text-underline-offset:0.2em;}}
.selvedge-footer__newsletter-form{{display:grid;grid-template-columns:1fr auto;gap:0;align-items:stretch;max-width:480px;margin:var(--wp--preset--spacing--md) auto 0;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--sm,4px);overflow:hidden;background:var(--wp--preset--color--base);}}
.selvedge-footer__newsletter-label{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}}
.selvedge-footer__newsletter-input{{border:0;background:transparent;padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);min-width:0;}}
.selvedge-footer__newsletter-input:focus{{outline:none;}}
.selvedge-footer__newsletter-submit{{border:0;border-left:1px solid var(--wp--preset--color--border);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;padding:0 var(--wp--preset--spacing--lg);cursor:pointer;transition:background 160ms ease;}}
.selvedge-footer__newsletter-submit:hover{{background:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);}}
{SENTINEL_CLOSE_PHASE_D_FOOTER}"""


# ---------------------------------------------------------------------------
# Phase E: per-theme distinctive polish.
# ---------------------------------------------------------------------------
# Scoped via the `body.theme-<slug>` class injected by each theme's
# `// === BEGIN body-class ===` block in `<theme>/functions.php`
# (migrated from the deleted `playground/wo-pages-mu.php`).
# These are the rules that should make the four demos read as four
# different storefronts even when looking only at the cart, PDP, or
# archive — the parts where a generic WC build looks identical across
# themes.
#
#   chonk    — brutalist hard-edged ATC, tilted Sale stickers, caption
#              pill on the PDP image.
#   obel     — sharp ATC (no radius, hairline border, wide tracking),
#              hairline rules between archive sections, chevron
#              breadcrumb separator.
#   selvedge — dark contrast swatches with cream selected ring, italic
#              display headings on archive sections, "Notes from the
#              workshop" attribution on PDP titles.
#   lysholm  — Nordic generous whitespace, centered shop hero,
#              tabular-nums prices everywhere.
SENTINEL_OPEN_PHASE_E = "/* wc-tells-phase-e-distinctive */"
SENTINEL_CLOSE_PHASE_E = "/* /wc-tells-phase-e-distinctive */"
CSS_PHASE_E = f"""{SENTINEL_OPEN_PHASE_E}
body.theme-chonk .single-product .single_add_to_cart_button,body.theme-chonk .wp-block-button .wp-block-button__link,body.theme-chonk .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button{{border-radius:0 !important;border-width:2px !important;border-style:solid !important;border-color:var(--wp--preset--color--contrast) !important;background:var(--wp--preset--color--contrast) !important;color:var(--wp--preset--color--base) !important;font-family:var(--wp--preset--font-family--display) !important;font-weight:var(--wp--custom--font-weight--medium,500) !important;letter-spacing:var(--wp--custom--letter-spacing--widest,0.16em) !important;text-transform:uppercase !important;padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--xl) !important;box-shadow:4px 4px 0 0 var(--wp--preset--color--accent) !important;transition:transform 120ms ease,box-shadow 120ms ease !important;}}
body.theme-chonk .single-product .single_add_to_cart_button:hover,body.theme-chonk .wp-block-button .wp-block-button__link:hover,body.theme-chonk .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover{{transform:translate(-2px,-2px) !important;box-shadow:6px 6px 0 0 var(--wp--preset--color--accent) !important;background:var(--wp--preset--color--contrast) !important;color:var(--wp--preset--color--base) !important;}}
body.theme-chonk .onsale,body.theme-chonk .wc-block-product-collection .wc-block-components-product-sale-badge,body.theme-chonk .wc-block-grid__product-onsale{{position:absolute;top:var(--wp--preset--spacing--sm);left:var(--wp--preset--spacing--sm);z-index:2;background:var(--wp--preset--color--accent);color:var(--wp--preset--color--contrast);font-family:var(--wp--preset--font-family--display);font-weight:var(--wp--custom--font-weight--medium,500);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--widest,0.16em);text-transform:uppercase;padding:var(--wp--preset--spacing--2-xs) var(--wp--preset--spacing--sm);border-radius:0;transform:rotate(-6deg);box-shadow:2px 2px 0 0 var(--wp--preset--color--contrast);}}
body.theme-chonk .single-product .wp-block-post-featured-image{{position:relative;}}
body.theme-chonk .single-product .wp-block-post-featured-image::after{{content:"Tap to zoom";position:absolute;bottom:var(--wp--preset--spacing--md);left:var(--wp--preset--spacing--md);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider,0.08em);text-transform:uppercase;padding:var(--wp--preset--spacing--2-xs) var(--wp--preset--spacing--sm);border-radius:var(--wp--custom--radius--pill,9999px);pointer-events:none;}}
body.theme-obel .single-product .single_add_to_cart_button,body.theme-obel .wp-block-button .wp-block-button__link,body.theme-obel .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button{{border-radius:0 !important;border:1px solid var(--wp--preset--color--contrast) !important;background:var(--wp--preset--color--base) !important;color:var(--wp--preset--color--contrast) !important;letter-spacing:var(--wp--custom--letter-spacing--widest,0.18em) !important;text-transform:uppercase !important;padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--2-xl) !important;font-weight:var(--wp--custom--font-weight--regular,400) !important;}}
body.theme-obel .single-product .single_add_to_cart_button:hover,body.theme-obel .wp-block-button .wp-block-button__link:hover,body.theme-obel .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover{{background:var(--wp--preset--color--contrast) !important;color:var(--wp--preset--color--base) !important;}}
body.theme-obel .wc-block-product-template>li,body.theme-obel .wc-block-product-collection .wp-block-post,body.theme-obel .products .product{{border-bottom:1px solid var(--wp--preset--color--border);padding-bottom:var(--wp--preset--spacing--lg);}}
body.theme-obel .woocommerce-breadcrumb,body.theme-obel .wc-block-breadcrumbs,body.theme-obel nav.woocommerce-breadcrumb{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider,0.08em);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
body.theme-obel .woocommerce-breadcrumb a,body.theme-obel .wc-block-breadcrumbs a{{color:var(--wp--preset--color--secondary);text-decoration:none;}}
body.theme-obel .woocommerce-breadcrumb a:hover,body.theme-obel .wc-block-breadcrumbs a:hover{{color:var(--wp--preset--color--contrast);}}
body.theme-obel .woocommerce-breadcrumb,body.theme-obel .wc-block-breadcrumbs{{display:flex;flex-wrap:wrap;gap:var(--wp--preset--spacing--xs);align-items:center;}}
body.theme-obel .woocommerce-breadcrumb>a:not(:last-child)::after,body.theme-obel .wc-block-breadcrumbs__item:not(:last-child)::after{{content:"›";display:inline-block;margin-left:var(--wp--preset--spacing--xs);color:var(--wp--preset--color--tertiary,var(--wp--preset--color--border));}}
body.theme-selvedge .wo-swatch--color{{background:var(--wp--preset--color--contrast);border-color:var(--wp--preset--color--contrast);}}
body.theme-selvedge .wo-swatch--color .wo-swatch__dot{{box-shadow:inset 0 0 0 1px rgba(255,255,255,0.16);}}
body.theme-selvedge .wo-swatch[aria-pressed="true"],body.theme-selvedge .wo-swatch--color[aria-pressed="true"]{{box-shadow:0 0 0 2px var(--wp--preset--color--base),0 0 0 4px var(--wp--preset--color--accent);}}
body.theme-selvedge .single-product .product_title,body.theme-selvedge .wo-archive-hero__title,body.theme-selvedge .wc-block-cart__totals-title,body.theme-selvedge .woocommerce-MyAccount-content h2,body.theme-selvedge .wo-recs>.wp-block-heading{{font-style:italic;letter-spacing:var(--wp--custom--letter-spacing--tight,-0.02em);}}
body.theme-selvedge .single-product .product_title::after{{content:"Notes from the workshop.";display:block;margin-top:var(--wp--preset--spacing--xs);font-style:normal;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider,0.08em);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
body.theme-lysholm .wc-block-product-collection,body.theme-lysholm .wc-block-cart,body.theme-lysholm .wc-block-checkout,body.theme-lysholm .single-product .product{{padding-block:var(--wp--preset--spacing--3-xl);}}
body.theme-lysholm .wo-archive-hero,body.theme-lysholm .wo-archive-hero__inner{{text-align:center;align-items:center;justify-items:center;}}
body.theme-lysholm .wo-archive-hero__lede{{max-width:48ch;margin-inline:auto;}}
body.theme-lysholm .price,body.theme-lysholm .wc-block-components-product-price,body.theme-lysholm .woocommerce-Price-amount,body.theme-lysholm .wc-block-formatted-money-amount,body.theme-lysholm .wc-block-components-totals-item__value,body.theme-lysholm .wc-block-components-product-price ins,body.theme-lysholm .wc-block-components-product-price del{{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1,"lnum" 1;letter-spacing:0;}}
body.theme-lysholm .wp-block-product-collection .wp-block-post,body.theme-lysholm .wc-block-grid__product{{padding:var(--wp--preset--spacing--md);}}
body.theme-foundry.theme-foundry .wc-block-mini-cart__footer-actions a:hover,body.theme-foundry.theme-foundry .wc-block-mini-cart__footer-actions .wc-block-components-button:hover,body.theme-foundry.theme-foundry .wc-block-components-totals-coupon__button:hover,body.theme-foundry.theme-foundry .wc-block-components-totals-coupon button:hover,body.theme-foundry.theme-foundry .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover,body.theme-foundry.theme-foundry .wc-block-cart__submit-container a.wc-block-cart__submit-button:hover,body.theme-foundry.theme-foundry .wc-block-components-checkout-place-order-button:hover,body.theme-foundry.theme-foundry .wp-block-woocommerce-order-confirmation-downloads .button:hover,body.theme-foundry.theme-foundry .woocommerce-MyAccount-content form .button:hover,body.theme-foundry.theme-foundry .woocommerce-orders-table .button:hover,body.theme-foundry.theme-foundry .wo-empty__cta--primary:hover,body.theme-foundry.theme-foundry .selvedge-footer__newsletter-submit:hover{{background:var(--wp--preset--color--accent);color:var(--wp--preset--color--base);}}
body.theme-bauhaus.theme-bauhaus .single-product .single_add_to_cart_button,body.theme-bauhaus.theme-bauhaus .wp-block-button .wp-block-button__link,body.theme-bauhaus.theme-bauhaus .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button{{border-radius:0 !important;border:0 !important;background:var(--wp--preset--color--accent) !important;color:var(--wp--preset--color--base) !important;font-family:var(--wp--preset--font-family--display) !important;font-weight:var(--wp--custom--font-weight--regular,400) !important;letter-spacing:var(--wp--custom--letter-spacing--wider,0.06em) !important;text-transform:uppercase !important;padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--2-xl) !important;}}
body.theme-bauhaus.theme-bauhaus .single-product .single_add_to_cart_button:hover,body.theme-bauhaus.theme-bauhaus .wp-block-button .wp-block-button__link:hover,body.theme-bauhaus.theme-bauhaus .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover{{background:var(--wp--preset--color--contrast) !important;color:var(--wp--preset--color--base) !important;}}
body.theme-bauhaus.theme-bauhaus .onsale,body.theme-bauhaus.theme-bauhaus .wc-block-product-collection .wc-block-components-product-sale-badge,body.theme-bauhaus.theme-bauhaus .wc-block-grid__product-onsale{{position:absolute;top:var(--wp--preset--spacing--sm);left:var(--wp--preset--spacing--sm);z-index:2;width:var(--wp--preset--spacing--2-xl);height:var(--wp--preset--spacing--2-xl);display:grid;place-items:center;border-radius:9999px;background:var(--wp--preset--color--accent);color:var(--wp--preset--color--base);font-family:var(--wp--preset--font-family--display);font-weight:var(--wp--custom--font-weight--regular,400);font-size:var(--wp--preset--font-size--xs);letter-spacing:0;text-transform:uppercase;padding:0;}}
body.theme-bauhaus.theme-bauhaus .wo-archive-hero,body.theme-bauhaus.theme-bauhaus .wo-archive-hero__inner{{padding-block:var(--wp--preset--spacing--3-xl);}}
body.theme-bauhaus.theme-bauhaus .wp-block-product-collection .wp-block-post,body.theme-bauhaus.theme-bauhaus .wc-block-grid__product{{border-top:1px solid var(--wp--preset--color--contrast);padding-block:var(--wp--preset--spacing--lg);}}
body.theme-bauhaus.theme-bauhaus .wo-archive-hero__title,body.theme-bauhaus.theme-bauhaus .single-product .product_title,body.theme-bauhaus.theme-bauhaus .wc-block-cart__totals-title{{letter-spacing:var(--wp--custom--letter-spacing--wider,0.04em);text-transform:uppercase;}}
{SENTINEL_CLOSE_PHASE_E}"""


# ----------------------------------------------------------------------
# Phase F — distinctive payment-icon chrome
# ----------------------------------------------------------------------
# Phase C ships ONE base treatment for `.wo-payment-icons__icon` (a
# 40×26 transparent container with 4px corners). That neutral base is
# fine as a fallback, but if every theme renders the trust strip with
# byte-identical chrome, the strip becomes a "standard" element — the
# exact "feels like a default WooCommerce site" smell we're trying to
# kill.
#
# Each theme overrides the pill chrome here so the strip reads in its
# own voice:
#   chonk    — sticker pile: 0 radius, 2px contrast border, brutalist
#              2×2 contrast shadow. Reads as hand-applied stickers.
#   obel     — paper stamp: warm hairline border, 4px corners. Reads
#              as a printed mark on cream.
#   selvedge — newsroom rule: hairline bottom only, 0 radius. Reads
#              as inline editorial badges, not buttons.
#   lysholm  — floating chip: full pill, no border, soft elevation.
#              Reads as a Nordic minimalist chip.
#
# Phase C's `.wo-payment-icons__icon{overflow:hidden}` clips the SVG's
# inner rounded rect to whatever shape Phase F dictates, so the brand
# colors fill the new corner radius cleanly with no SVG edits needed.
#
# RULE: when a new "premium chrome" surface ships in Phase A–E (cart
# sidebar, primary CTA, sale badge, hero, …), it MUST either differ
# per theme in its base rule body or land here in Phase F so each
# theme expresses its own visual voice. See the
# `check_distinctive_chrome` rule in bin/check.py.
SENTINEL_OPEN_PHASE_F = "/* wc-tells-phase-f-pay-pill */"
SENTINEL_CLOSE_PHASE_F = "/* /wc-tells-phase-f-pay-pill */"
CSS_PHASE_F = f"""{SENTINEL_OPEN_PHASE_F}
body.theme-chonk .wo-payment-icons__icon{{border:2px solid var(--wp--preset--color--contrast);border-radius:0;box-shadow:2px 2px 0 0 var(--wp--preset--color--contrast);}}
body.theme-obel .wo-payment-icons__icon{{border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md,4px);}}
body.theme-selvedge .wo-payment-icons__icon{{border:0;border-bottom:1px solid var(--wp--preset--color--border);border-radius:0;}}
body.theme-lysholm .wo-payment-icons__icon{{border:0;border-radius:var(--wp--custom--radius--pill,9999px);box-shadow:0 1px 2px rgba(0,0,0,0.06);}}
body.theme-basalt .wo-payment-icons__icon{{border:1px solid var(--wp--preset--color--border);border-radius:2px;background:var(--wp--preset--color--surface);}}
body.theme-foundry .wo-payment-icons__icon{{border:1px solid var(--wp--preset--color--accent);border-radius:var(--wp--custom--radius--sm,3px);background:var(--wp--preset--color--base);box-shadow:0 1px 0 var(--wp--preset--color--contrast);}}
body.theme-bauhaus .wo-payment-icons__icon{{border:0;border-radius:0;background:var(--wp--preset--color--surface);outline:2px solid var(--wp--preset--color--contrast);outline-offset:0;}}
{SENTINEL_CLOSE_PHASE_F}"""


# ----------------------------------------------------------------------
# Phase G — distinctive cart/checkout sidebar voices
# ----------------------------------------------------------------------
# The cart sidebar and the checkout sidebar are the two heaviest "card
# surfaces" on a WC storefront — every shopper looking at a totals
# panel reads the surface treatment as a brand statement. Phase A–E
# left the BASE rule for `.wc-block-checkout__sidebar` as plumbing-
# only (overflow-wrap, word-break, hyphens) which means every theme
# rendered the checkout summary as an unpainted, edgeless block: the
# textbook "looks like a default Woo checkout" smell. The cart
# sidebar got partial per-theme treatments in earlier phases but
# obel and lysholm still resolved to byte-identical chrome because
# the cart sidebar in the base CSS (Phase A wc-tells) is hard-coded
# to one warm-minimal default and only chonk + selvedge had bothered
# to override it.
#
# Phase G fixes both:
#   - Cart sidebar: lysholm gets its own Nordic-warm override
#     (surface bg, soft accent hairline, 16px radius, soft elevation)
#     so it's no longer a clone of obel.
#   - Checkout sidebar: every theme gets a per-theme override that
#     mirrors its OWN cart-sidebar treatment, so within a single
#     theme the cart card and the checkout card read as the same
#     visual language.
#
# This is exactly the pattern enforced by `check_distinctive_chrome`
# in bin/check.py: shared "standard" base + per-theme `body.theme-<slug>`
# overrides that visibly differentiate.
SENTINEL_OPEN_PHASE_G = "/* wc-tells-phase-g-card-voices */"
SENTINEL_CLOSE_PHASE_G = "/* /wc-tells-phase-g-card-voices */"
CSS_PHASE_G = f"""{SENTINEL_OPEN_PHASE_G}
body.theme-chonk .wc-block-cart__sidebar,body.theme-chonk .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--base);border:4px solid var(--wp--preset--color--contrast);border-radius:0;box-shadow:8px 8px 0 var(--wp--preset--color--contrast);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-obel .wc-block-cart__sidebar,body.theme-obel .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-selvedge .wc-block-cart__sidebar,body.theme-selvedge .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:0;display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-lysholm .wc-block-cart__sidebar,body.theme-lysholm .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--accent-soft,var(--wp--preset--color--border));border-radius:var(--wp--custom--radius--lg,16px);box-shadow:0 2px 12px rgba(0,0,0,0.04);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-basalt .wc-block-cart__sidebar,body.theme-basalt .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:0;display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);}}
body.theme-foundry .wc-block-cart__sidebar,body.theme-foundry .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--base);border-top:2px solid var(--wp--preset--color--accent);border-bottom:2px solid var(--wp--preset--color--accent);border-left:0;border-right:0;border-radius:0;display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-bauhaus .wc-block-cart__sidebar,body.theme-bauhaus .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--surface);border:2px solid var(--wp--preset--color--contrast);border-radius:0;display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);position:relative;}}
body.theme-bauhaus .wc-block-cart__sidebar::before,body.theme-bauhaus .wc-block-checkout__sidebar::before{{content:"";position:absolute;top:calc(-1 * var(--wp--preset--spacing--xs));right:calc(-1 * var(--wp--preset--spacing--xs));width:var(--wp--preset--spacing--lg);height:var(--wp--preset--spacing--lg);background:var(--wp--preset--color--accent);pointer-events:none;}}
{SENTINEL_CLOSE_PHASE_G}"""


# ----------------------------------------------------------------------
# Phase H — totals-block internal padding (the "edge-to-edge order summary"
#           regression)
# ----------------------------------------------------------------------
# Why this exists:
#   Phase G paints the per-theme card chrome (background + border + radius
#   + shadow + voice-distinct details) on `.wc-block-cart__sidebar` and
#   `.wc-block-checkout__sidebar`. Those rules also set `padding: xl` on
#   the sidebar wrapper. That worked for older WC blocks where the
#   sidebar wrapper WAS the visible card surface.
#
#   In current WC blocks (9.x+) the visible "Order summary" card is
#   actually the INNER block `.wp-block-woocommerce-cart-totals-block`
#   (or `.wp-block-woocommerce-checkout-totals-block`), which renders
#   inside the sidebar wrapper at width:100%. The sidebar wrapper's
#   `padding: xl` insets the inner block from the wrapper edges, but
#   on themes where the sidebar wrapper is NOT painted (or is painted
#   the same color as the page, like Selvedge's dark base) the inner
#   totals block looks like the card and any of its content (Phase C's
#   `::before` "Order summary" pseudo-label + the SUBTOTAL / coupon row
#   / total) sits flush against the inner block's edge. That's the
#   "screenshot bug" — content butts up against the visual panel edge
#   because the painted edge is the inner totals block, not the outer
#   wrapper, and the inner block has no padding of its own.
#
# Why a separate chunk:
#   Phase G is per-theme voice. This rule is theme-agnostic plumbing
#   that prevents the regression on every theme present and future. By
#   emitting it as its own sentinel-bracketed chunk we can tighten the
#   rule (or add new totals selectors as WC adds new totals containers)
#   without touching any per-theme voice rule.
#
# Why `xl` and not larger:
#   Card surfaces hold dense compound content (subtotals, taxes, totals,
#   coupon input, primary CTA). `lg` (~24-40px) visibly cramps that
#   stack against the panel edge. `xl` (~40-64px) is the floor for the
#   panel to "breathe". Anything larger is theme-specific and belongs
#   in a per-theme voice override (Phase G).
#
# Enforced by:
#   `bin/check.py::check_wc_totals_blocks_padded` (independent of
#   background paint — the rule applies even on themes whose totals
#   block ends up unpainted, because it ALWAYS becomes the visible
#   card on current WC).
SENTINEL_OPEN_PHASE_H = "/* wc-tells-phase-h-totals-padding */"
SENTINEL_CLOSE_PHASE_H = "/* /wc-tells-phase-h-totals-padding */"
CSS_PHASE_H = f"""{SENTINEL_OPEN_PHASE_H}
.wp-block-woocommerce-cart-totals-block,.wp-block-woocommerce-checkout-totals-block{{padding:var(--wp--preset--spacing--xl);box-sizing:border-box;}}
{SENTINEL_CLOSE_PHASE_H}"""


# ----------------------------------------------------------------------
# Phase I — form-input chrome (the "Selvedge checkout is unreadable"
#           regression)
# ----------------------------------------------------------------------
# Why this exists:
#   WooCommerce checkout blocks ship their own input/label CSS that
#   hardcodes a WHITE input wrapper background and inherits the page
#   `color` for the floating label. On a light-base theme that's fine
#   (cream-on-white inputs are visible because the page color is dark
#   anyway). On a DARK-base theme like Selvedge (where the page
#   inherits `color: var(--wp--preset--color--contrast)` = #EDE3CE
#   cream), every checkout `<label>` inherits the cream color and
#   sits over WC's white input wrapper background. Result: every form
#   field label renders cream-on-white at ~1.27:1 contrast — the
#   entire checkout form is invisible on Selvedge. axe flags it as
#   `color-contrast` on `label[for="email"]`,
#   `label[for="shipping-first_name"]`, etc. (9 labels in the
#   field-focus snap).
#
#   The fix is to take ownership of the form-input chrome at
#   sufficient specificity to beat WC's per-element rules: paint the
#   wrapper AND the input itself with `--surface` (theme-aware),
#   force the input text to `--contrast`, and force every floating
#   label to `--secondary`. On every theme this yields a legible
#   form ensemble (light themes get dark text on cream-ish surface;
#   dark themes get cream text on dark-brown surface). Selvedge's
#   checkout becomes readable; the other themes pick up consistency.
#
# Why `body` prefix on every selector:
#   WC ships its rules at specificity ~`(0,0,2)` (e.g.
#   `.wc-block-components-text-input input`). A bare top-level rule
#   at the same specificity loses or wins based on source-order
#   (WC's stylesheet is enqueued AFTER theme.json's inline `styles.
#   css` in many setups, so it can win). The `body` prefix bumps us
#   to `(0,1,2)` — just enough to win without resorting to
#   `!important`. We deliberately AVOID `!important` here because
#   per-theme voice rules (Phase E, Phase G) need to be able to
#   reskin form inputs without fighting an `!important` cascade,
#   and reviewers (and future agents) are tired of seeing
#   `!important` keep creeping into the codebase.
#
# Why these selectors specifically:
#   * `.wc-block-components-text-input` — the wrapper that holds the
#     floating label + input on every WC checkout text field
#     (email, name, address, city, zip, phone). This is the element
#     axe sees as the white background underneath the label.
#   * `.wc-block-components-text-input input` — the actual editable
#     input. Forcing its background to surface (instead of inheriting
#     transparent or being painted white by WC) keeps the wrapper +
#     input visually unified, so the floating label has a single
#     consistent background under it.
#   * `.wc-block-components-select`, `.wc-block-components-select
#     select`, `.wc-blocks-components-select__label` — the
#     country/region + state selects on the shipping/billing form.
#     Same pattern, same fix.
#   * `.wc-block-components-textarea`, `.wc-block-components-
#     textarea textarea` — the order notes textarea. Same pattern.
#   * Label rules — paint every floating label with `--secondary`
#     (which is mid-gray on light themes and warm-tan on dark
#     themes; both pass ≥4.5:1 against `--surface` in every
#     palette in this monorepo).
#
# Enforced by:
#   No new check (yet). The existing
#   `check_hover_state_legibility` infrastructure could be extended
#   to walk `:focus`-state form-input rules and resolve
#   label-vs-wrapper contrast in a follow-up pass; for now this
#   chunk is the source of truth and any future regression will
#   show up in `bin/snap.py check`'s axe sweep.
SENTINEL_OPEN_PHASE_I = "/* wc-tells-phase-i-form-input-chrome */"
SENTINEL_CLOSE_PHASE_I = "/* /wc-tells-phase-i-form-input-chrome */"
CSS_PHASE_I = f"""{SENTINEL_OPEN_PHASE_I}
body .wc-block-components-text-input.wc-block-components-text-input input[type],body .wc-block-components-select.wc-block-components-select select,body .wc-blocks-components-select.wc-blocks-components-select select,body .wc-block-components-textarea.wc-block-components-textarea textarea{{background:var(--wp--preset--color--surface);color:var(--wp--preset--color--contrast);border:1px solid var(--wp--preset--color--border);}}
body .wc-block-components-text-input.wc-block-components-text-input label,body .wc-block-components-select.wc-block-components-select label,body .wc-blocks-components-select.wc-blocks-components-select label,body .wc-blocks-components-select.wc-blocks-components-select .wc-blocks-components-select__label,body .wc-block-components-textarea.wc-block-components-textarea label{{color:var(--wp--preset--color--contrast);background:var(--wp--preset--color--surface);}}
body .wc-block-components-text-input.wc-block-components-text-input input[type]::placeholder,body .wc-block-components-textarea.wc-block-components-textarea textarea::placeholder{{color:var(--wp--preset--color--contrast);opacity:0.7;}}
body .wc-block-components-text-input.wc-block-components-text-input input[type]:focus,body .wc-block-components-select.wc-block-components-select select:focus,body .wc-blocks-components-select.wc-blocks-components-select select:focus,body .wc-block-components-textarea.wc-block-components-textarea textarea:focus{{outline:none;border-color:var(--wp--preset--color--contrast);box-shadow:0 0 0 3px var(--wp--preset--color--accent-soft,var(--wp--preset--color--border));}}
body .wc-block-components-checkbox .wc-block-components-checkbox__input{{background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);}}
{SENTINEL_CLOSE_PHASE_I}"""


# ----------------------------------------------------------------------
# Phase J — Aero iridescent / glassy chrome (Y2K bubble pop)
# ----------------------------------------------------------------------
# Aero is the Y2K iridescent-pastel variant. The base aero theme.json
# was cloned from obel and inherited obel's hairline-square button
# voice in Phase E. That voice is wrong for aero — the brief is
# "bubbly chrome": rounded glass buttons, iridescent body wash,
# chrome wordmark, sparkle product cards, soft pastel surfaces.
#
# Phase J ships AFTER Phase E so its rules win on `body.theme-aero`
# selectors via source order. Phase J only carries `body.theme-aero`
# selectors so it has zero effect on the four other themes. The chunk
# is appended to every theme's styles.css (idempotent + theme-agnostic
# bytes) but only paints when the body class matches.
#
# Why it lives in this script and not aero/theme.json directly:
#   - Keeps every visual override on every theme reachable from one
#     file (the script is the audit trail for "which voice does
#     theme X speak in which surface?").
#   - Keeps aero's per-theme deltas idempotent + diff-clean — the
#     chunk is sentinel-bracketed so re-running the script never
#     duplicates rules.
SENTINEL_OPEN_PHASE_J = "/* wc-tells-phase-j-aero-iridescent */"
SENTINEL_CLOSE_PHASE_J = "/* /wc-tells-phase-j-aero-iridescent */"
CSS_PHASE_J = f"""{SENTINEL_OPEN_PHASE_J}
body.theme-aero{{background:linear-gradient(135deg,var(--wp--preset--color--base) 0%,var(--wp--preset--color--subtle) 28%,var(--wp--preset--color--accent-soft) 60%,var(--wp--preset--color--base) 100%) fixed;background-attachment:fixed;}}
body.theme-aero .wp-site-blocks{{background:transparent;}}
body.theme-aero .wp-block-button .wp-block-button__link,body.theme-aero .wp-block-button__link,body.theme-aero .wc-block-components-product-button__button,body.theme-aero .single-product .single_add_to_cart_button,body.theme-aero .single_add_to_cart_button,body.theme-aero .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button,body.theme-aero .wc-block-cart__submit-container a.wc-block-cart__submit-button,body.theme-aero .wc-block-components-checkout-place-order-button{{border-radius:var(--wp--custom--radius--pill,9999px) !important;border:1px solid rgba(255,255,255,0.6) !important;background:linear-gradient(180deg,rgba(255,255,255,0.7) 0%,var(--wp--preset--color--accent) 55%,var(--wp--preset--color--contrast) 100%) !important;color:var(--wp--preset--color--surface) !important;font-family:var(--wp--preset--font-family--sans) !important;font-weight:var(--wp--custom--font-weight--bold,700) !important;letter-spacing:var(--wp--custom--letter-spacing--wide,0.04em) !important;text-transform:none !important;padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--xl) !important;box-shadow:inset 0 1px 0 rgba(255,255,255,0.9),inset 0 -2px 4px rgba(45,31,102,0.25),0 8px 18px rgba(0,153,194,0.35) !important;text-shadow:0 1px 0 rgba(45,31,102,0.4) !important;transition:transform 160ms ease,box-shadow 160ms ease,background 160ms ease !important;}}
body.theme-aero .wp-block-button .wp-block-button__link:hover,body.theme-aero .wp-block-button__link:hover,body.theme-aero .wc-block-components-product-button__button:hover,body.theme-aero .single-product .single_add_to_cart_button:hover,body.theme-aero .single_add_to_cart_button:hover,body.theme-aero .wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover,body.theme-aero .wc-block-components-checkout-place-order-button:hover{{background:linear-gradient(180deg,rgba(255,255,255,0.85) 0%,var(--wp--preset--color--accent-soft) 30%,var(--wp--preset--color--accent) 100%) !important;transform:translateY(-2px) !important;box-shadow:inset 0 1px 0 rgba(255,255,255,1),inset 0 -2px 6px rgba(45,31,102,0.3),0 14px 28px rgba(0,153,194,0.4) !important;color:var(--wp--preset--color--contrast) !important;}}
body.theme-aero .wp-block-site-title a,body.theme-aero .wp-block-site-title{{background:linear-gradient(180deg,var(--wp--preset--color--contrast) 0%,var(--wp--preset--color--secondary) 35%,var(--wp--preset--color--accent) 50%,var(--wp--preset--color--secondary) 65%,var(--wp--preset--color--contrast) 100%);-webkit-background-clip:text;background-clip:text;color:var(--wp--preset--color--contrast) !important;-webkit-text-fill-color:transparent;font-family:var(--wp--preset--font-family--display) !important;letter-spacing:0.02em !important;}}
body.theme-aero .wp-block-site-title a:hover{{background:linear-gradient(180deg,var(--wp--preset--color--primary-hover) 0%,var(--wp--preset--color--secondary) 35%,var(--wp--preset--color--accent) 50%,var(--wp--preset--color--secondary) 65%,var(--wp--preset--color--primary-hover) 100%);-webkit-background-clip:text;background-clip:text;color:var(--wp--preset--color--primary-hover) !important;-webkit-text-fill-color:transparent;}}
body.theme-aero .wc-block-product-template>li,body.theme-aero .wc-block-product-collection .wp-block-post,body.theme-aero .products li.product,body.theme-aero .wp-block-product{{position:relative;background:rgba(255,255,255,0.55);border:1px solid rgba(255,255,255,0.75);border-radius:var(--wp--custom--radius--xl,36px);padding:var(--wp--preset--spacing--md);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);box-shadow:inset 0 1px 0 rgba(255,255,255,0.9),0 12px 28px rgba(74,63,135,0.14);overflow:hidden;}}
body.theme-aero .wc-block-product-template>li::after,body.theme-aero .wc-block-product-collection .wp-block-post::after,body.theme-aero .products li.product::after,body.theme-aero .wp-block-product::after{{content:"\\2728";position:absolute;top:10px;right:14px;font-size:14px;line-height:1;opacity:0.7;pointer-events:none;filter:drop-shadow(0 1px 0 rgba(255,255,255,0.8));}}
body.theme-aero .wc-block-product-template>li img,body.theme-aero .wc-block-product-collection .wp-block-post img,body.theme-aero .products li.product img,body.theme-aero .wp-block-product img{{border-radius:var(--wp--custom--radius--lg,24px);}}
body.theme-aero .onsale,body.theme-aero span.onsale,body.theme-aero .wc-block-product-collection .wc-block-components-product-sale-badge{{background:linear-gradient(135deg,var(--wp--preset--color--iridescent) 0%,var(--wp--preset--color--accent-soft) 50%,var(--wp--preset--color--muted) 100%) !important;color:var(--wp--preset--color--contrast) !important;border:1px solid rgba(255,255,255,0.8) !important;border-radius:var(--wp--custom--radius--pill,9999px) !important;padding:6px 14px !important;font-family:var(--wp--preset--font-family--display) !important;text-transform:none !important;letter-spacing:0.01em !important;box-shadow:inset 0 1px 0 rgba(255,255,255,0.9),0 4px 10px rgba(74,63,135,0.18) !important;transform:rotate(-4deg) !important;}}
body.theme-aero .wc-block-cart__sidebar,body.theme-aero .wc-block-checkout__sidebar,body.theme-aero .wp-block-woocommerce-cart-totals-block,body.theme-aero .wp-block-woocommerce-checkout-totals-block{{background:rgba(255,255,255,0.6) !important;border:1px solid rgba(255,255,255,0.8) !important;border-radius:var(--wp--custom--radius--xl,36px) !important;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:inset 0 1px 0 rgba(255,255,255,0.9),0 18px 40px rgba(74,63,135,0.18) !important;}}
body.theme-aero .wo-payment-icons__icon{{background:linear-gradient(180deg,var(--wp--preset--color--surface) 0%,var(--wp--preset--color--chrome) 60%,var(--wp--preset--color--surface) 100%) !important;border:1px solid rgba(255,255,255,0.8) !important;border-radius:var(--wp--custom--radius--lg,24px) !important;box-shadow:inset 0 1px 0 rgba(255,255,255,0.95),0 2px 6px rgba(74,63,135,0.18) !important;}}
body.theme-aero .wp-block-search__inside-wrapper,body.theme-aero input[type="text"],body.theme-aero input[type="email"],body.theme-aero input[type="url"],body.theme-aero textarea,body.theme-aero select{{border-radius:var(--wp--custom--radius--lg,24px) !important;background:rgba(255,255,255,0.7) !important;border:1px solid rgba(212,196,242,0.8) !important;}}
body.theme-aero .wp-block-navigation:not(.is-vertical) .wp-block-navigation-item__content{{padding:var(--wp--preset--spacing--xs) var(--wp--preset--spacing--md) !important;border-radius:var(--wp--custom--radius--pill,9999px) !important;transition:background 160ms ease,color 160ms ease !important;}}
body.theme-aero .wp-block-navigation:not(.is-vertical) .wp-block-navigation-item__content:hover{{background:rgba(255,255,255,0.55) !important;color:var(--wp--preset--color--primary-hover) !important;}}
body.theme-aero .wp-block-navigation:not(.is-vertical) .wp-block-navigation-item__content::after{{display:none !important;}}
body.theme-aero .wp-block-navigation.is-vertical .wp-block-navigation-item__content{{padding-inline:0 !important;border-radius:0 !important;transition:color 160ms ease !important;}}
body.theme-aero .wp-block-navigation.is-vertical .wp-block-navigation-item__content:hover{{background:transparent !important;color:var(--wp--preset--color--primary-hover) !important;}}
body.theme-aero h1,body.theme-aero h2,body.theme-aero .wp-block-heading{{text-shadow:0 1px 0 rgba(255,255,255,0.7);}}
{SENTINEL_CLOSE_PHASE_J}"""


# ----------------------------------------------------------------------
# Phase K — Aero front-page "signal strip" promise band
# ----------------------------------------------------------------------
# A 4-tile chrome-chip row that lives between the hero and the featured
# product collection on aero/templates/front-page.html. Three reasons it
# exists as its own chunk instead of inline in Phase J:
#   1. It's a NEW section unique to aero — no equivalent in obel /
#      chonk / selvedge / lysholm — so it changes the front-page
#      structural fingerprint and lets aero pass
#      `check_front_page_unique_layout` against obel (the two themes
#      previously shared the same `[hero-split, group, group]` shape
#      and only got past the check because the slug differed).
#   2. The Phase J sentinel is already locked in every theme's
#      styles.css; appending into the same chunk would require force
#      re-injection. A new phase keeps every existing theme byte-stable.
#   3. Scoped to `body.theme-aero .aero-signal-strip` so it has zero
#      effect on every other theme (the markup itself only ships in
#      aero/templates/front-page.html).
SENTINEL_OPEN_PHASE_K = "/* wc-tells-phase-k-aero-signal-strip */"
SENTINEL_CLOSE_PHASE_K = "/* /wc-tells-phase-k-aero-signal-strip */"
#
# No `!important` here on purpose: Phase K targets bespoke aero markup
# (`.aero-signal-strip`, `.aero-signal-chip`) that no WC plugin paints,
# so there's no cascade fight to win and the rules win on specificity
# alone. Adding `!important` would trip `bin/check.py`'s
# `check_no_important` rule for no good reason — that rule's allowlist
# is reserved for chunks where WC plugin CSS has property-level
# `!important` we have to override (see Phases A, C, E, J).
CSS_PHASE_K = f"""{SENTINEL_OPEN_PHASE_K}
body.theme-aero .aero-signal-strip{{background:linear-gradient(90deg,rgba(255,255,255,0.55) 0%,rgba(214,196,242,0.45) 28%,rgba(167,210,238,0.45) 55%,rgba(255,224,243,0.45) 82%,rgba(255,255,255,0.55) 100%);border-top:1px solid rgba(255,255,255,0.8);border-bottom:1px solid rgba(255,255,255,0.8);box-shadow:inset 0 1px 0 rgba(255,255,255,0.95),inset 0 -1px 0 rgba(74,63,135,0.08);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);}}
body.theme-aero .aero-signal-strip .aero-signal-strip__row{{gap:var(--wp--preset--spacing--lg);}}
body.theme-aero .aero-signal-strip .aero-signal-chip{{margin:0;padding:6px 14px;border-radius:var(--wp--custom--radius--pill,9999px);background:linear-gradient(180deg,rgba(255,255,255,0.85) 0%,rgba(255,255,255,0.55) 100%);border:1px solid rgba(255,255,255,0.8);color:var(--wp--preset--color--contrast);font-family:var(--wp--preset--font-family--sans);font-weight:600;letter-spacing:var(--wp--custom--letter-spacing--wide,0.04em);text-transform:uppercase;box-shadow:inset 0 1px 0 rgba(255,255,255,0.95),0 4px 10px rgba(74,63,135,0.10);}}
@media (max-width: 781px){{body.theme-aero .aero-signal-strip .aero-signal-strip__row{{gap:var(--wp--preset--spacing--xs);}} body.theme-aero .aero-signal-strip .aero-signal-chip{{padding:5px 10px;}}}}
{SENTINEL_CLOSE_PHASE_K}"""


# ----------------------------------------------------------------------
# Phase L — WooCommerce notices (banner + validation + snackbar)
# ----------------------------------------------------------------------
# WooCommerce's notice surfaces are the loudest "default WooCommerce" tell
# on the entire shop AFTER the cart sidebar and the catalog-sorting
# select — they appear at exactly the moments a shopper is paying the
# most attention (failed login, invalid coupon, sold-out variation,
# checkout validation error, "item removed from cart") and ship in five
# different markup shapes that all paint differently:
#
#   1. `.wc-block-components-notice-banner.is-info|is-warning|is-error|
#      is-success` — the modern WC Blocks notice surface (Cart, Checkout,
#      Mini-Cart, Store Notices block). WC ships it with a hardcoded
#      pastel-pill voice (round corners, white background, sans-serif,
#      stock SVG icon in a tinted circle on the left). It looks
#      identical on every WooCommerce site on the internet, which makes
#      the moment it appears the moment the storefront stops feeling
#      bespoke.
#   2. `.wc-block-components-validation-error` — per-field inline error
#      shown beneath checkout/billing inputs after a failed submit.
#      WC paints it red Helvetica with a stock exclamation-circle SVG.
#   3. `.wc-block-components-snackbar-notice` — the floating bottom-
#      center toast WC injects when `useStoreSnackbarNotices()` fires
#      (e.g. cart line removal "Item removed. Undo?"). WC paints it
#      black-on-white with a hard square corner and a bottom shadow.
#   4. `.wc-block-store-notices` / `.woocommerce-notices-wrapper` /
#      `.wc-block-components-notices` — the wrapper containers that
#      hold any of the above. They ship with default `margin` and
#      no `display: none` when empty, which leaves a stray gap above
#      every Cart and Checkout view.
#   5. `.woocommerce-message` / `.woocommerce-error` / `.woocommerce-info`
#      — the legacy classic-template notices used by My Account login,
#      `wc_add_notice()` from PHP, the Lost Password flow, and any
#      `[woocommerce_*]` shortcode page. The original `wc-tells` block
#      at the top of this file renders them flat-uppercase-hairline,
#      which clashes with the modern Blocks banner voice (different
#      font weight, different padding, different border treatment).
#
# Phase L unifies all five surfaces under a single token-driven voice:
#
#   * Wrapper containers collapse when empty (`:empty { display: none }`)
#     so the gap-above-cart goes away when there's nothing to show.
#   * The banner itself uses `body` selector prefix to bump specificity
#     to (0,1,N), enough to win over WC's plugin CSS at (0,0,2-3) by
#     specificity AND source order, without needing `!important` (Phase L
#     is intentionally NOT in `IMPORTANT_ALLOWED_SENTINELS`; the cascade
#     wins on its own).
#   * Variant signal color comes from each theme's existing palette
#     tokens (`--wp--preset--color--info|success|warning|error`) — every
#     theme already declares them with brand-tuned values. The whole
#     chunk is therefore theme-agnostic bytes that paint per-theme
#     signal automatically.
#   * The tinted background uses CSS `color-mix(in oklab, <signal> 8%,
#     var(--wp--preset--color--surface))` so each variant gets a
#     subtle wash of its own color over the theme's surface — readable
#     on light AND dark themes. `color-mix()` is supported in every
#     browser in WooCommerce's official compatibility matrix
#     (Chrome 111+, Safari 16.2+, Firefox 113+, May 2023+); on older
#     browsers the declaration is ignored and the wrapper falls back
#     to the plain surface color, which still reads correctly.
#   * Typography matches the rest of the storefront chrome: theme
#     sans family, `sm` size, normal letter-spacing, normal case
#     (the original chunk uppercased everything, which made notice
#     copy unreadable at a glance).
#   * The leading SVG icon WC blocks injects gets colored to match
#     the variant signal via `currentColor` propagation.
#   * Inline-validation errors get the `error` token's color directly,
#     plus a subtle inset border on the failed input wrapper so the
#     shopper can see WHICH field failed without hunting.
#   * Snackbars use the theme's contrast/base inversion (dark bubble
#     on light themes, light bubble on dark themes) with a pill
#     radius for a clearly transient affordance distinct from the
#     persistent banner.
#   * Inline action buttons inside notices ("Undo", "Dismiss",
#     "Apply now") render as underlined links that signal hover with
#     a thicker decoration (NOT a `color: accent` flip — that would
#     trip `check_hover_state_legibility` on themes whose accent
#     collapses against the body background, e.g. chonk's #FFE600
#     yellow vs cream).
#
# Enforced by:
#   `bin/check.py::check_wc_notices_styled` — fails if Phase L's
#   sentinel block is missing from any theme's `theme.json` root
#   `styles.css`, or if the block is present but doesn't carry the
#   canonical surface restyles.
SENTINEL_OPEN_PHASE_L = "/* wc-tells-phase-l-notices */"
SENTINEL_CLOSE_PHASE_L = "/* /wc-tells-phase-l-notices */"
CSS_PHASE_L = f"""{SENTINEL_OPEN_PHASE_L}
body .woocommerce-notices-wrapper:empty,body .wc-block-store-notices:empty,body .wc-block-components-notices:empty,body .wc-block-store-notices > .woocommerce-notices-wrapper:empty{{display:none;margin:0;padding:0;}}
body .woocommerce-notices-wrapper,body .wc-block-store-notices,body .wc-block-components-notices{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--sm);margin-block:var(--wp--preset--spacing--md);}}
body .wc-block-components-notice-banner,body .woocommerce-message,body .woocommerce-error,body .woocommerce-info{{position:relative;display:flex;align-items:flex-start;justify-content:flex-start;gap:var(--wp--preset--spacing--sm);margin:0;padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--lg);border:1px solid var(--wp--preset--color--border);border-left-width:4px;border-radius:var(--wp--custom--radius--md,6px);background:var(--wp--preset--color--surface);color:var(--wp--preset--color--contrast);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--regular,400);letter-spacing:normal;text-transform:none;line-height:1.45;list-style:none;box-shadow:0 1px 0 rgba(0,0,0,0.04);}}
body .wc-block-components-notice-banner.is-info,body .woocommerce-info{{border-left-color:var(--wp--preset--color--info);background:color-mix(in oklab,var(--wp--preset--color--info) 8%,var(--wp--preset--color--surface));color:var(--wp--preset--color--contrast);}}
body .wc-block-components-notice-banner.is-success,body .woocommerce-message{{border-left-color:var(--wp--preset--color--success);background:color-mix(in oklab,var(--wp--preset--color--success) 8%,var(--wp--preset--color--surface));color:var(--wp--preset--color--contrast);}}
body .wc-block-components-notice-banner.is-warning{{border-left-color:var(--wp--preset--color--warning);background:color-mix(in oklab,var(--wp--preset--color--warning) 9%,var(--wp--preset--color--surface));color:var(--wp--preset--color--contrast);}}
body .wc-block-components-notice-banner.is-error,body .woocommerce-error{{border-left-color:var(--wp--preset--color--error);background:color-mix(in oklab,var(--wp--preset--color--error) 9%,var(--wp--preset--color--surface));color:var(--wp--preset--color--contrast);}}
body .wc-block-components-notice-banner > svg,body .wc-block-components-notice-banner__content + svg{{flex:0 0 auto;width:20px;height:20px;margin-block-start:2px;}}
body .wc-block-components-notice-banner.is-info > svg{{color:var(--wp--preset--color--info);fill:currentColor;}}
body .wc-block-components-notice-banner.is-success > svg{{color:var(--wp--preset--color--success);fill:currentColor;}}
body .wc-block-components-notice-banner.is-warning > svg{{color:var(--wp--preset--color--warning);fill:currentColor;}}
body .wc-block-components-notice-banner.is-error > svg{{color:var(--wp--preset--color--error);fill:currentColor;}}
body .wc-block-components-notice-banner__content{{flex:1 1 auto;margin:0;padding:0;font:inherit;color:inherit;line-height:inherit;}}
body .wc-block-components-notice-banner__content > p,body .wc-block-components-notice-banner__content > a,body .woocommerce-message > a,body .woocommerce-info > a,body .woocommerce-error > a{{color:inherit;}}
body .wc-block-components-notice-banner .wc-block-components-button:not(.wc-block-components-button--primary),body .wc-block-components-notice-banner .wc-block-components-notice-banner__dismiss,body .woocommerce-message .button,body .woocommerce-info .button,body .woocommerce-error .button,body .woocommerce-message .woocommerce-Button,body .woocommerce-info .woocommerce-Button,body .woocommerce-error .woocommerce-Button{{margin-inline-start:auto;background:transparent;border:0;padding:var(--wp--preset--spacing--2-xs) 0 var(--wp--preset--spacing--2-xs) var(--wp--preset--spacing--md);color:inherit;font-family:inherit;font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium,500);letter-spacing:var(--wp--custom--letter-spacing--wider,0.04em);text-transform:uppercase;text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px;cursor:pointer;}}
body .wc-block-components-notice-banner .wc-block-components-button:not(.wc-block-components-button--primary):hover,body .woocommerce-message .button:hover,body .woocommerce-info .button:hover,body .woocommerce-error .button:hover,body .woocommerce-message .woocommerce-Button:hover,body .woocommerce-info .woocommerce-Button:hover,body .woocommerce-error .woocommerce-Button:hover{{text-decoration-thickness:2px;text-decoration-color:currentColor;}}
body .wc-block-components-validation-error{{display:block;margin-block-start:var(--wp--preset--spacing--2-xs);padding:0;background:transparent;border:0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium,500);color:var(--wp--preset--color--error);letter-spacing:normal;text-transform:none;line-height:1.4;}}
body .wc-block-components-validation-error > p{{margin:0;color:inherit;font:inherit;}}
body .wc-block-components-text-input.has-error input,body .wc-block-components-text-input.has-error textarea,body .wc-block-components-select.has-error select,body .wc-block-components-textarea.has-error textarea{{border-color:var(--wp--preset--color--error);box-shadow:0 0 0 1px var(--wp--preset--color--error) inset;}}
body .wc-block-components-text-input.has-error label,body .wc-block-components-select.has-error label,body .wc-block-components-textarea.has-error label{{color:var(--wp--preset--color--error);}}
body .wc-block-components-notices__snackbar,body .wc-block-components-notice-snackbar-list{{position:fixed;left:50%;bottom:var(--wp--preset--spacing--lg);transform:translateX(-50%);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);max-width:calc(100vw - var(--wp--preset--spacing--lg) * 2);z-index:1000;pointer-events:none;}}
body .wc-block-components-snackbar-notice,body .wc-block-components-snackbar-list__notice,body .wc-block-components-snackbar{{pointer-events:auto;display:inline-flex;align-items:center;gap:var(--wp--preset--spacing--md);margin:0;padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--lg);border:0;border-radius:var(--wp--custom--radius--pill,9999px);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium,500);letter-spacing:var(--wp--custom--letter-spacing--wider,0.04em);text-transform:uppercase;line-height:1.3;box-shadow:0 8px 24px rgba(0,0,0,0.18);}}
body .wc-block-components-snackbar-notice .wc-block-components-button,body .wc-block-components-snackbar .wc-block-components-button,body .wc-block-components-snackbar-list__notice .wc-block-components-button{{background:transparent;border:0;padding:0;color:inherit;font:inherit;text-transform:inherit;letter-spacing:inherit;text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px;cursor:pointer;}}
body .wc-block-components-snackbar-notice .wc-block-components-button:hover,body .wc-block-components-snackbar .wc-block-components-button:hover{{text-decoration-thickness:2px;text-decoration-color:currentColor;}}
{SENTINEL_CLOSE_PHASE_L}"""


# ---------------------------------------------------------------------------
# PHASE M -- a11y contrast tweaks for upstream-WC component states that
# rely on per-theme palette tokens and happen to land on insufficient-
# contrast combos in one or more themes.
#
# Each block is body-class-scoped so the intent (and the affected theme)
# is documented inline; using the `body.theme-<slug>` namespace also
# means a future palette swap on one theme cannot accidentally re-break
# the other four. The three offenders this chunk addresses, in the order
# they fail axe-core 4.10's `color-contrast` rule on a fresh
# `bin/snap.py shoot --all`:
#
#   M1. `.single_add_to_cart_button.disabled,
#         .single_add_to_cart_button:disabled`
#       Variable-product PDPs ship the button disabled until a variation
#       is picked. Without an explicit disabled-state rule the browser
#       drops the `body.theme-<slug>` paint and falls back to its UA
#       greyed-out chrome (a flat ~#7B7974 / ~#8A8987 background under
#       the theme's `--base` text). Ratios land at 3.20-4.42 across
#       chonk / lysholm / obel / selvedge / foundry / aero -- all below
#       the 4.5:1 AA threshold for body text. We restate the same
#       `--contrast` ground + `--base` ink the active state uses, set
#       `opacity:1` so the cursor change carries the disabled affordance
#       instead of fading the label, and add `cursor:not-allowed` so
#       pointer users still perceive the disabled state.
#
#       Coverage history: chonk/lysholm/obel/selvedge shipped first
#       (caught by the original axe sweep on those four themes). Foundry
#       and aero were added 2026-04-24 after the
#       `check_disabled_button_contrast_per_theme` static check
#       generalised the failure surface across all six themes (axe found
#       foundry's khaki disabled paint at 2.18:1 on /product/ when no
#       variant is picked).
#
#   M2. `.wp-block-comment-reply-link a, .comment-reply-link`
#       chonk / lysholm / obel paint the comment Reply link in their
#       editorial accent (chonk #FFE600 yellow, lysholm #C9A97C sand,
#       obel #C07241 terracotta) on the cream/off-white page. Ratios
#       land at 1.12 / 2.04 / 3.50 -- way below the 4.5:1 floor for body
#       text. Use `--contrast` for the resting color (high ratio against
#       cream backgrounds) and keep the editorial accent on hover so the
#       brand voice survives where contrast requirements relax for
#       interactive states.
#
#   M3. `body.theme-selvedge .wc-block-cart-items .is-disabled .wc-block-cart-item__product`
#       (and the matching `__total` sibling chain). WC Blocks adds
#       `.is-disabled` to a cart-item row during the brief loading flash
#       between `Remove` click and DOM swap. The default rule reduces
#       opacity, which flattens selvedge's `--secondary` (#B09878) text
#       to an effective ~#82796B against the `--base` (#160F08) cart-
#       sidebar background -- 4.42:1, just shy of 4.5. We restate the
#       muted color at full opacity so the skeleton state stays legible
#       while preserving the visual "this row is busy" affordance via
#       the WC Blocks-supplied skeleton placeholders.
#
#   M4. `.wc-block-components-notice-banner > .wc-block-components-notice-banner__content .wc-forward`
#       WC Blocks ships this exact selector in three stylesheets with
#       `color: rgb(47,47,47) !important; opacity:.7`. On Selvedge's
#       near-black account pages that yields 1.24:1 contrast for the
#       "Browse products" empty-orders CTA. Specificity cannot beat a
#       property-level `!important`, so the smallest honest fix is a
#       Selvedge-scoped important rule that restores the theme contrast
#       token and full opacity.
#
# (M2 and M3 deliberately ship per-theme: aero already passes thanks to
# its high-contrast accent + light-on-dark cart palette; selvedge passes
# the M2 case because its accent is darker than the others. Adding
# unscoped rules would silently re-paint surfaces those themes have
# already tuned.)
# ---------------------------------------------------------------------------
SENTINEL_OPEN_PHASE_M = "/* wc-tells-phase-m-a11y-contrast */"
SENTINEL_CLOSE_PHASE_M = "/* /wc-tells-phase-m-a11y-contrast */"

def _build_phase_m_css() -> str:
    disabled_rules = "\n".join(
        f"body.theme-{slug} .single_add_to_cart_button.disabled,"
        f"body.theme-{slug} .single_add_to_cart_button:disabled,"
        f"body.theme-{slug} .single_add_to_cart_button.wc-variation-selection-needed"
        "{background:var(--wp--preset--color--contrast) !important;"
        "color:var(--wp--preset--color--base) !important;"
        "border-color:var(--wp--preset--color--contrast) !important;"
        "opacity:1 !important;cursor:not-allowed;}"
        for slug in discover_themes(stages=())
    )
    return f"""{SENTINEL_OPEN_PHASE_M}
{disabled_rules}
body.theme-chonk .wp-block-comment-reply-link a,body.theme-chonk .comment-reply-link,body.theme-lysholm .wp-block-comment-reply-link a,body.theme-lysholm .comment-reply-link,body.theme-obel .wp-block-comment-reply-link a,body.theme-obel .comment-reply-link,body.theme-basalt .wp-block-comment-reply-link a,body.theme-basalt .comment-reply-link{{color:var(--wp--preset--color--contrast) !important;}}
body.theme-chonk .wp-block-comment-reply-link a:hover,body.theme-chonk .comment-reply-link:hover,body.theme-lysholm .wp-block-comment-reply-link a:hover,body.theme-lysholm .comment-reply-link:hover,body.theme-obel .wp-block-comment-reply-link a:hover,body.theme-obel .comment-reply-link:hover,body.theme-basalt .wp-block-comment-reply-link a:hover,body.theme-basalt .comment-reply-link:hover{{text-decoration:underline !important;text-decoration-thickness:2px !important;text-underline-offset:3px !important;text-decoration-color:var(--wp--preset--color--accent) !important;}}
body .wc-block-cart-items .is-disabled,body .wc-block-cart-items .is-disabled .wc-block-cart-item__product,body .wc-block-cart-items .is-disabled .wc-block-cart-item__total,body .wc-block-cart-items .is-disabled .wc-block-cart-item__product *,body .wc-block-cart-items .is-disabled .wc-block-cart-item__total *{{color:var(--wp--preset--color--contrast) !important;opacity:1 !important;}}
body.theme-selvedge .wc-block-components-notice-banner > .wc-block-components-notice-banner__content .wc-forward{{color:var(--wp--preset--color--contrast) !important;opacity:1 !important;}}
{SENTINEL_CLOSE_PHASE_M}"""


CSS_PHASE_M = _build_phase_m_css()


# ---------------------------------------------------------------------------
# Follow-up chunk: Phase N loading-skeleton paint.
# ---------------------------------------------------------------------------
# Replaces the old Phase A `display:none!important` blanket (see the
# Phase A comment block #4 for the post-mortem). WC Blocks renders
# `.wc-block-components-skeleton__element` placeholder bars while the
# cart-store / checkout-store XHR finishes; the skeleton is the right
# loading affordance, but at default-WC neutral grey it reads as
# "stock WC, not part of this theme". This chunk repaints two
# surfaces in each theme's tokens so the loading state carries the
# brand voice instead of looking like an unstyled placeholder:
#
#   N1. The bar itself (`.wc-block-components-skeleton__element`)
#       gets `--subtle` for its ground colour and our shared
#       `--radius--md` so the bar shape matches every other painted
#       card in the theme.
#
#   N2. The shimmer pseudo (`.wc-block-components-skeleton__element
#       :after`, plus the static variant) gets a horizontal
#       `--border` gradient that animates over `--subtle`. We
#       deliberately don't override `animation`/`animation-duration`
#       — WC's keyframes are fine; we only need to swap the colour.
#
# Specificity: WC's deepest skeleton selector inside the checkout
# order-summary is `.wc-block-components-order-summary
# .wc-block-components-skeleton--cart-line-items-checkout
# .wc-block-components-order-summary-item__description
# .wc-block-components-skeleton__element` -- (0,4,0). We use the
# doubled-class trick (4× the same class) prefixed with `body` so
# every rule lands at (0,4,1), beating the deepest WC selector
# without `!important`. Same idiom Phase I uses on input chrome.
#
# The corresponding `.wc-block-components-loading-mask` (covers an
# in-place update like a quantity bump) intentionally stays at WC's
# default semi-transparent overlay — it works against any palette
# because it reads as a tint of whatever sits behind it. If a future
# theme needs to recolour it, add the rule here so the mask stays a
# documented part of the loading-state contract.
SENTINEL_OPEN_PHASE_N = "/* wc-tells-phase-n-skeleton */"
SENTINEL_CLOSE_PHASE_N = "/* /wc-tells-phase-n-skeleton */"
_SK = ".wc-block-components-skeleton__element"
_SKS = ".wc-block-components-skeleton__element--static"
_SK4 = f"{_SK}{_SK}{_SK}{_SK}"
_SKS4 = f"{_SKS}{_SKS}{_SKS}{_SKS}"
CSS_PHASE_N = f"""{SENTINEL_OPEN_PHASE_N}
body {_SK4}{{background-color:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);}}
body {_SK4}:after,body {_SKS4}:after{{background:linear-gradient(90deg,transparent,var(--wp--preset--color--border),transparent);}}
{SENTINEL_CLOSE_PHASE_N}"""


# ---------------------------------------------------------------------------
# Follow-up chunk: Phase O — order-summary line-item description padding.
# ---------------------------------------------------------------------------
# WC blocks core ships
#   .wc-block-components-order-summary
#     .wc-block-components-order-summary-item__description{
#       padding:4px 12px 12px 24px;
#     }
# That 24px left-padding + 12px right-padding eats ~36px of horizontal
# space inside a 99px-wide grid track on the 360px desktop checkout
# sidebar, leaving just ~63px for the product name. Long product names
# such as "Pocket-Sized Thunder" then wrap mid-word as
# "Pocket-/Sized/Thun-/der", which the snap.py `word-broken` heuristic
# (longest unbroken token measured against the rendered element width)
# correctly flags as accidental. Bringing the padding down to a 12px /
# 8px pair restores enough room for any product name in the catalogue
# while still keeping the image / text gutter visually distinct.
#
# Same fix applies on the cart page (which uses
# `wc-block-cart-items` rather than the order-summary block) — we
# tighten its corresponding `wc-block-cart-item__product` cell so the
# cart line-items have the same forgiving wrap behaviour.
SENTINEL_OPEN_PHASE_O = "/* wc-tells-phase-o-cart-name-padding */"
SENTINEL_CLOSE_PHASE_O = "/* /wc-tells-phase-o-cart-name-padding */"
# Selectors are intentionally double/triple-classed (`.foo.foo .bar.bar`)
# so they outrank WC Blocks' own defaults. WC ships
# `.wc-block-components-order-summary .wc-block-components-skeleton--cart-line-items-checkout .wc-block-components-order-summary-item__description`
# at (0,3,0) and `.is-medium table.wc-block-cart-items .wc-block-cart-items__row .wc-block-cart-item__product`
# at (0,4,1) -- a naive (0,2,0) override loses the cascade. The
# doubled-class form keeps the rules cosmetically the same selector
# (same compound, same rightmost match) while bumping specificity to
# (0,4,0) and (0,5,0) respectively. check.py's
# check_wc_specificity_winnable() enforces this on every commit.
CSS_PHASE_O = f"""{SENTINEL_OPEN_PHASE_O}
.wc-block-components-order-summary.wc-block-components-order-summary .wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description{{padding:4px 8px 12px 12px;}}
.wc-block-cart-items.wc-block-cart-items.wc-block-cart-items .wc-block-cart-item__product.wc-block-cart-item__product{{padding-left:12px;padding-right:8px;}}
{SENTINEL_CLOSE_PHASE_O}"""

# wc-tells phase-p: tighten product-name typography in cramped sidebar
# / cart cells so hyphenated tokens like `Pocket-Sized` (or their
# theme-uppercased form `POCKET-SIZED`) fit the description box
# without triggering snap.py's `word-broken` heuristic. We pair a
# smaller font-size with disabled uppercase transform / wide
# letter-spacing because chonk's eyebrow style otherwise inflates
# token width by ~20%.
SENTINEL_OPEN_PHASE_P = "/* wc-tells-phase-p-cart-name-typography */"
SENTINEL_CLOSE_PHASE_P = "/* /wc-tells-phase-p-cart-name-typography */"
# Same doubled/tripled-class trick as Phase O. The deepest WC Blocks
# default for `.wc-block-components-product-name` lives at
# `.wp-block-woocommerce-cart .wp-block-woocommerce-cart-cross-sells-block .cross-sells-product div .wc-block-components-product-name`
# = (0,4,1). The doubled form lifts our selectors to (0,5,0)/(0,5,1),
# both of which beat (0,4,1). For the trailing `h3`-rightmost cases,
# the parent class is repeated 5x so `.foo.foo.foo.foo.foo h3` lands
# at (0,5,1).
CSS_PHASE_P = f"""{SENTINEL_OPEN_PHASE_P}
.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar .wc-block-components-product-name.wc-block-components-product-name,.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar .wc-block-components-product-name.wc-block-components-product-name,.wc-block-cart-items.wc-block-cart-items.wc-block-cart-items .wc-block-cart-item__product.wc-block-cart-item__product .wc-block-components-product-name.wc-block-components-product-name,.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar h3.wc-block-components-product-name.wc-block-components-product-name,.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar .wc-block-components-order-summary-item.wc-block-components-order-summary-item h3,.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar h3{{font-size:12px;text-transform:none;letter-spacing:0;line-height:1.35;}}
{SENTINEL_CLOSE_PHASE_P}"""

# wc-tells phase-q: real-bug cleanup batch derived from the post-PR-14
# snap gallery (after detector noise fixes landed):
#
#   1. Classic PDP review form overflow (#review_form_wrapper, #respond,
#      #commentform) — was overflowing its column by 50px on desktop /
#      42px on tablet because WP's default `<input style="width:75%">`
#      + 4px border + 8px padding + box-sizing:content-box exceeds the
#      column. Constrain via box-sizing:border-box + max-width:100% +
#      min-width:0 (so flex/grid parents don't refuse to shrink).
#      Kills ~78 element-overflow-x findings/run on every PDP cell.
#
#   2. wo-archive-hero h1 line-height 1 -> 1.15. The `line-height:1`
#      crops the inline-box at the cap height; descender + leading
#      escapes the box, browsers report scrollHeight > clientHeight by
#      ~12-14% of font-size (10-14px on the 5xl heading). Italic display
#      faces make this worse because their letterforms tilt below
#      baseline. Bumping to 1.15 absorbs the hang within the line-box;
#      visually identical for single-line "Shop"/"Curiosities" titles
#      because the parent already centers + baseline-aligns.
#      Kills ~30 heading-clipped-vertical findings/run on shop +
#      category archives across all 5 themes.
#
#   3. Cart line-item Remove "x" button tap target. The wc-block default
#      renders the icon inside an `<a class="wc-block-cart-item__remove-link">`
#      with `display:inline` and a 16px SVG -- effective tap target
#      ~16x18px, well under the 32px floor. We inline-flex it to
#      32x32 minimum and visually center the icon. WCAG 2.5.5
#      Recommended target size is 24x24, but our snap heuristic and
#      most A11y guidance both want 32x32 for "primary" tap targets.
#      Kills ~80 tap-target-too-small findings/run on cart-filled.
#
#   4. wc-block quantity-selector "+/-" buttons. Same problem as the
#      Remove icon: 24x24 default, fails the 32px tap-target rule. The
#      input itself was rendering at 40px wide which clipped the "3"
#      label by 6px (the "button-label-overflow" rule). Bump buttons
#      to 36x36 and input to min-width:48px to give two-digit quantities
#      headroom. (40px input + 24px-each buttons -> 36px buttons +
#      48px input keeps the overall stepper width approximately
#      unchanged at ~120px, so cart-line layout doesn't reflow.)
#      Kills ~80 tap-target findings + 60 button-label-overflow findings.
#
SENTINEL_OPEN_PHASE_Q = "/* wc-tells-phase-q-real-bug-cleanup */"
SENTINEL_CLOSE_PHASE_Q = "/* /wc-tells-phase-q-real-bug-cleanup */"
CSS_PHASE_Q = f"""{SENTINEL_OPEN_PHASE_Q}
.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #respond,.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #review_form_wrapper,.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #review_form,.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #commentform,.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #commentform p{{box-sizing:border-box;max-width:100%;min-width:0;}}
.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #commentform input[type=text],.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #commentform input[type=email],.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #commentform input[type=url],.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #commentform textarea,.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews.wp-block-woocommerce-product-reviews #commentform select{{box-sizing:border-box;max-width:100%;width:100%;min-width:0;}}
.wo-archive-hero__title.wo-archive-hero__title{{line-height:1.15;}}
.wc-block-cart-item__remove-link.wc-block-cart-item__remove-link.wc-block-cart-item__remove-link.wc-block-cart-item__remove-link.wc-block-cart-item__remove-link{{display:inline-flex;align-items:center;justify-content:center;min-width:32px;min-height:32px;}}
.wc-block-components-quantity-selector__button.wc-block-components-quantity-selector__button.wc-block-components-quantity-selector__button.wc-block-components-quantity-selector__button.wc-block-components-quantity-selector__button{{min-width:36px;min-height:36px;}}
.wc-block-components-quantity-selector__input.wc-block-components-quantity-selector__input.wc-block-components-quantity-selector__input.wc-block-components-quantity-selector__input.wc-block-components-quantity-selector__input{{min-width:48px;}}
{SENTINEL_CLOSE_PHASE_Q}"""

# wc-tells phase-r: round-2 cleanup after observing the post-Phase-Q
# gallery. Targets the next bucket of real bugs, picked from the
# remaining clusters (not detector tweaks):
#
#   1. `.wp-block-post-title` and `h2.wp-block-heading` line-height bump.
#      Same root cause as the wo-archive-hero fix — `line-height:1`
#      crops descenders + italic letterform tilt. Singular post / page
#      titles ("CART", "JOURNAL", post titles) lose 6-12px to the same
#      bug. Not patching the WP core block style; we doubled-class our
#      own rule to win the cascade. ~120 heading-clipped findings/run.
#
#   2. `.wc-block-mini-cart__button` min-width:48px. Mini-cart count
#      "3" overflows the button by 6px because WC sizes the button to
#      hug the icon + 1-digit count; 2-digit counts (and any double-
#      width glyph) clip. ~60 button-label-overflow findings/run.
#
#   3. `.wc-block-checkout__sidebar` overflow-wrap:anywhere. WC's
#      strict `word-break:keep-all` on the sidebar product names is
#      causing 16 word-broken findings/run on long product names
#      that share a sidebar column with a tight gap.
#
#   4. Aero announcement bar: `.alignfull > div.wp-block-group` housing
#      the "✦ HOLOGRAPHIC SHIPPING OVER $50 ✦ CATCH THE NEW DROP →"
#      strip needs `flex-wrap:wrap` so it doesn't push 117px off-canvas
#      on tablet/mobile. Targets only aero (the only theme with that
#      strip) by scoping to `body.theme-aero .wp-site-blocks > div >
#      header.alignfull > div.wp-block-group:first-child`. The whole
#      strip is a 2-paragraph flex row; wrapping is the right
#      responsive behaviour. ~120 element-overflow-x +
#      ~20 horizontal-overflow findings/run.
#
SENTINEL_OPEN_PHASE_R = "/* wc-tells-phase-r-real-bug-cleanup-2 */"
SENTINEL_CLOSE_PHASE_R = "/* /wc-tells-phase-r-real-bug-cleanup-2 */"
CSS_PHASE_R = f"""{SENTINEL_OPEN_PHASE_R}
.wp-block-post-title.wp-block-post-title.wp-block-post-title.wp-block-post-title{{line-height:1.25;padding-bottom:0.05em;}}
h2.wp-block-heading.wp-block-heading.wp-block-heading.wp-block-heading{{line-height:1.3;padding-bottom:0.05em;}}
.wc-block-mini-cart__button.wc-block-mini-cart__button.wc-block-mini-cart__button.wc-block-mini-cart__button.wc-block-mini-cart__button{{min-width:60px;padding-left:8px;padding-right:8px;}}
.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar{{overflow-wrap:anywhere;}}
.aero-header.aero-header .is-nowrap.is-nowrap{{flex-wrap:wrap;}}
{SENTINEL_CLOSE_PHASE_R}"""


# wc-tells phase-s: the post-Phase-R / post-batch-4 cleanup. The
# remaining clusters in the gallery are a tight set of real bugs the
# previous CSS chunks didn't fully neutralise:
#
#   1. wo-archive-hero h1 ("Curiosities", "Range") at the 5xl preset
#      blows past the mobile viewport: an 11-character serif headline
#      renders ~385px wide inside a 294px content column, pushing the
#      whole document scrollWidth 43px past the 390px iPhone viewport.
#      Cascades into 14× horizontal-overflow + 14× wp-site-blocks
#      overflow + 12× wp-block-template-part overflow (one per
#      mobile route, one per theme). Fixed with a `clamp()` so the
#      headline scales down on narrow viewports while keeping the
#      desktop typographic intent. Also bumps line-height to 1.3 +
#      adds padding-block:0.05em so descenders / italic ascenders
#      don't trip the heading-clipped detector.
#
#   2. wo-account-intro__title ("WELCOME BACK TO …") same root cause
#      at line-height:1, ~22 heading-clipped findings/run.
#
#   3. h1.wp-block-heading (page titles like "CART", "CHECKOUT",
#      "JOURNAL") missed by the post-title rule — the Phase R rule
#      targets `.wp-block-post-title`, page titles use plain
#      `.wp-block-heading`. Adds the matching line-height bump.
#
#   4. WC product-template `.wc-block-components-product-button`
#      buttons inside the 4-column shop grid: at tablet width each
#      button is 120px wide but the default `padding: 12px 24px`
#      leaves only 72px for the label. Words >= 7 characters
#      ("Acquire", "Select options") spill 9-10px past the box on
#      every product card, every mobile/tablet shop+category route.
#      Shrinks padding to 8px and lets the link text wrap.
#
#   5. mini-cart button label "3" still overflows by 2px even after
#      the Phase R 60px min-width. The WC default uses `width:auto`
#      and the visible cart-count badge sits absolutely positioned
#      half-outside the button boundary; bumping min-width with
#      !important + adding right-padding for the badge clears it.
#
SENTINEL_OPEN_PHASE_S = "/* wc-tells-phase-s-real-bug-cleanup-3 */"
SENTINEL_CLOSE_PHASE_S = "/* /wc-tells-phase-s-real-bug-cleanup-3 */"
CSS_PHASE_S = f"""{SENTINEL_OPEN_PHASE_S}
.wo-archive-hero__title.wo-archive-hero__title.wo-archive-hero__title{{font-size:clamp(2rem,8vw,var(--wp--preset--font-size--5-xl));line-height:1.3;padding-block:0.05em;overflow-wrap:break-word;min-width:0;max-width:100%;}}
.wo-archive-hero__inner.wo-archive-hero__inner{{min-width:0;max-width:100%;}}
.wo-account-intro__title.wo-account-intro__title.wo-account-intro__title{{line-height:1.3;padding-block:0.05em;}}
h1.wp-block-heading.wp-block-heading.wp-block-heading.wp-block-heading{{line-height:1.25;padding-bottom:0.05em;}}
.wp-block-woocommerce-product-template .wc-block-components-product-button.wc-block-components-product-button .wp-block-button__link,.wp-block-woocommerce-product-collection .wc-block-components-product-button.wc-block-components-product-button .wp-block-button__link{{padding-left:8px;padding-right:8px;min-width:0;max-width:100%;white-space:normal;overflow-wrap:break-word;}}
{SENTINEL_CLOSE_PHASE_S}"""


# wc-tells phase-t: the post-Phase-S cleanup. Two specific real bugs
# that surfaced once the Phase R/S noise cleared:
#
#   1. wo-account-login-grid (the "Welcome back, sign in" grid that
#      wraps WC's login form on the my-account page when the visitor
#      is logged out) renders inside `.entry-content.alignwide >
#      .woocommerce` with a 220px content column. The inner login
#      copy ("PILOT ID … Welcome back to Aero. … Sign In") needs
#      314px and spills 94px past the box on EVERY my-account route
#      at desktop+wide (8 element-overflow-x findings/run, plus
#      visible truncation in the gallery). Force the grid to 1
#      column with `min-width:0` so the form fields and copy stay
#      inside the parent column.
#
#   2. Selvedge primary nav at tablet (768px viewport) needs 756px
#      of menu items inside a 705px alignwide content column —
#      cascades into 51px + 19px overflow findings on the alignwide
#      / alignfull / template-part / wp-site-blocks chain on every
#      route. Allow the primary nav row to wrap on tablet+mobile so
#      the menu reflows below the logo instead of forcing horizontal
#      scroll. Selvedge-only (other themes' headers fit at 768px).
#      Targets the alignfull header's nav container with high-spec
#      class chaining; falls back to `flex-wrap:wrap` which is
#      what the WP block editor expects when the nav doesn't fit.
#
SENTINEL_OPEN_PHASE_T = "/* wc-tells-phase-t-real-bug-cleanup-4 */"
SENTINEL_CLOSE_PHASE_T = "/* /wc-tells-phase-t-real-bug-cleanup-4 */"
# NOTE: the original Phase T also held a `@media (max-width:781px)`
# header flex-wrap rule scoped to `body.theme-{selvedge,chonk,lysholm}`.
# That enumeration was retired in favor of Phase GG's universal
# `.wp-site-blocks header.wp-block-group.alignfull` selector (which
# covers every theme on disk, current and future, without requiring a
# hand-edit every time a new theme ships). Leaving Phase T's sentinel
# intact so SENTINEL_CLOSE_PHASE_T remains a valid anchor for Phase U.
CSS_PHASE_T = f"""{SENTINEL_OPEN_PHASE_T}
.wo-account-login-grid.wo-account-login-grid.wo-account-login-grid{{display:grid;grid-template-columns:minmax(0,1fr);min-width:0;max-width:100%;}}
.wo-account-login-grid.wo-account-login-grid.wo-account-login-grid>*{{min-width:0;max-width:100%;overflow-wrap:break-word;}}
{SENTINEL_CLOSE_PHASE_T}"""


# wc-tells phase-u: a small set of remaining real bugs the post-Phase-T
# gallery exposed:
#
#   1. Heading line-height for the explicit big-font-size classes
#      `.has-6-xl-font-size` and `.has-3-xl-font-size`. The Phase R
#      `h2.wp-block-heading` rule clears the wrapped-headline case
#      but the chonk hero "MADE TO LAST. PRICED TO LIVE WITH." H1
#      uses `has-6-xl-font-size` which has its own line-height:1
#      coming from the preset, so the post-title rule loses the
#      cascade. Triple-classed selector restores the bump for
#      hero/section headings at the named font sizes (~42 heading-
#      clipped findings/run on chonk + selvedge home + section h1s).
#
#   2. wo-account-intro__title overflow-wrap. The "Welcome back to
#      Aero." headline rendering at 314px inside a 161px <aside>
#      cell wraps mid-word ("W-e-l-c-o-m-e") on every desktop+wide
#      my-account route, ~24 word-broken findings/run. Adding
#      overflow-wrap:anywhere lets the headline break on letterform
#      boundaries instead of producing a stair-step layout.
#
SENTINEL_OPEN_PHASE_U = "/* wc-tells-phase-u-real-bug-cleanup-5 */"
SENTINEL_CLOSE_PHASE_U = "/* /wc-tells-phase-u-real-bug-cleanup-5 */"
CSS_PHASE_U = f"""{SENTINEL_OPEN_PHASE_U}
.has-6-xl-font-size.has-6-xl-font-size.has-6-xl-font-size{{line-height:1.3;}}
.has-5-xl-font-size.has-5-xl-font-size.has-5-xl-font-size{{line-height:1.3;}}
.has-4-xl-font-size.has-4-xl-font-size.has-4-xl-font-size{{line-height:1.3;}}
.has-3-xl-font-size.has-3-xl-font-size.has-3-xl-font-size{{line-height:1.35;}}
.wo-account-intro__title.wo-account-intro__title.wo-account-intro__title{{overflow-wrap:anywhere;min-width:0;max-width:100%;}}
.wo-account-intro.wo-account-intro.wo-account-intro,.wo-account-intro.wo-account-intro.wo-account-intro>*{{min-width:0;max-width:100%;overflow-wrap:break-word;}}
{SENTINEL_CLOSE_PHASE_U}"""


# wc-tells phase-v: final cleanup batch covering the long-tail clusters
# the post-Phase-U gallery still surfaced:
#
#   1. Plain `h1.wp-block-heading` / `h2.wp-block-heading` (no font-size
#      preset class) clipping 5-9px on tablet wraps. The Phase-U bumps
#      only targeted .has-{3..6}-xl-font-size. Generic block heading
#      line-height needs the same 1.3 floor so descenders + wraps don't
#      poke past the heading's own clientHeight.
#
#   2. WooCommerce product-button covers BOTH `<button>` and `<a>`
#      forms (an anchor when the product is variable-with-options or
#      out-of-stock-with-cta). Phase-S only loosened `<button>` padding
#      so 16 obel "SELECT OPTIONS" anchors overflowed 19px. Same rule,
#      `a.wp-block-button__link` now included.
#
#   3. Mini-cart "items" badge button is 2px tight (overflow on the
#      "3" digit when font has wide numerals). Add 2px horizontal
#      breathing room without a min-width that would cascade-break
#      header layouts (lesson learnt in Phase S).
#
#   4. Checkout order-summary-cart-items: product titles inside the
#      collapsed accordion block force scrollWidth 14px past
#      clientWidth on desktop checkout-filled. Force min-width:0 +
#      overflow-wrap:anywhere on the cart-items block + its descendants
#      so the title wraps at the box edge instead of pushing.
#
# wc-tells phase-w: tap-target + order-summary fixes for the long-tail
# clusters that survived Phase V:
#
#   1. Pagination "Next Page" / "Previous Page" anchors render as
#      glyph-only links 25-30px tall on mobile, below the 32px touch
#      target floor. Pad to 32x32 with a generous hit-box.
#
#   2. Checkout `+ Add apartment, suite, etc.` toggle is a 14px-tall
#      `<span>` masquerading as a button — give it visible button
#      proportions on mobile so the user can actually tap it.
#
#   3. Checkout "Return to Cart" link similarly tiny on mobile;
#      same treatment.
#
#   4. WC `<button class="show-password-input">` (eye-icon button
#      next to the password field) renders 18x18 by default — bump
#      to 32x32 minimum.
#
#   5. Theme header navigation anchors at mobile (aero/obel) measure
#      ~16-22px tall as inline text; pad them so each link is a
#      proper 32px tap row.
#
#   6. Order-summary cart-items block in checkout: the layout grid
#      uses a fixed image column + flexible text column where the
#      text column's min-content (long product name) pushes the
#      whole block 14px past the parent. Force the text column to
#      `min-width: 0` so it shrinks gracefully; long names then wrap
#      via the Phase V product-name overflow-wrap rule. This is the
#      surgical version of the universal-`*` rule that backfired
#      in batch 9.
#
# Phase X — selvedge-pass cleanup (issued 2026-04-22)
#
# Bugs the user reported on selvedge that boil down to four shared
# WC-blocks structural defaults the earlier phases never neutralised:
#
#   1. PLACE ORDER button stretches full-form-column-width on checkout.
#      The bare `.wc-block-components-checkout-place-order-button` rule
#      from phase C sets `width:100%`, which is correct INSIDE the cart
#      `.wc-block-cart__submit-container` (the only CTA on that page) but
#      wrong on the checkout actions row, where the button shares space
#      with "Return to Cart". Constrain checkout-page button to auto width
#      with comfortable horizontal padding, and lay the actions row out
#      as a flex row so Return-to-Cart sits left and Place-Order sits
#      right without wrapping.
#
#   2. "Return to Cart" link wraps to two short stacked words next to the
#      oversized PLACE ORDER. Force `white-space:nowrap` and
#      `flex-shrink:0` so the link keeps its natural inline width.
#
#   3. Order-summary heading underline (the soft border-bottom WC paints
#      under `.wc-block-components-totals-wrapper` headings) extends past
#      the sidebar's left/right padding because the sidebar sets padding
#      on itself but the heading row spans the full content box. Pull the
#      underline inside the padded box by clamping the heading's box and
#      its border to the padded-content width.
#
#   4. Notices in the cart/checkout/account empty states still feel
#      "WooCommercy" — the phase-L baseline added a coloured left rail
#      and surface tint, but for selvedge we want a flatter, contrast-on-
#      base notice that matches the rest of the workshop card system
#      (no left rail, hairline border in the brand border colour, eyebrow
#      micro-typography, no coloured surface tint).
#
SENTINEL_OPEN_PHASE_X = "/* wc-tells-phase-x-selvedge-pass */"
SENTINEL_CLOSE_PHASE_X = "/* /wc-tells-phase-x-selvedge-pass */"
CSS_PHASE_X = f"""{SENTINEL_OPEN_PHASE_X}
.wc-block-checkout__actions_row.wc-block-checkout__actions_row{{display:flex;align-items:center;justify-content:space-between;gap:var(--wp--preset--spacing--md);flex-wrap:nowrap;padding-left:var(--wp--preset--spacing--xs);padding-right:var(--wp--preset--spacing--xs);}}
.wc-block-checkout__actions_row.wc-block-checkout__actions_row .wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button{{flex:0 0 auto;white-space:nowrap;min-height:32px;padding:6px var(--wp--preset--spacing--xs);overflow:visible;}}
.wc-block-checkout__actions_row.wc-block-checkout__actions_row.wc-block-checkout__actions_row .wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button > svg.wc-block-components-checkout-return-to-cart-button__svg{{flex:0 0 auto;margin-right:var(--wp--preset--spacing--2-xs);}}
.wc-block-checkout__actions_row.wc-block-checkout__actions_row.wc-block-checkout__actions_row .wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button > svg{{flex:0 0 auto;margin-right:var(--wp--preset--spacing--2-xs);}}
.wc-block-checkout__actions_row.wc-block-checkout__actions_row .wc-block-components-checkout-place-order-button.wc-block-components-checkout-place-order-button{{width:auto;flex:0 1 auto;min-width:200px;max-width:100%;padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--xl);}}
.wc-block-components-order-summary.wc-block-components-order-summary .wc-block-components-order-summary-item.wc-block-components-order-summary-item{{display:grid;grid-template-columns:48px minmax(0,1fr) auto;align-items:start;gap:var(--wp--preset--spacing--sm);min-width:0;}}
.wc-block-components-order-summary.wc-block-components-order-summary .wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description{{min-width:0;max-width:100%;}}
.wc-block-components-order-summary.wc-block-components-order-summary .wc-block-components-order-summary-item__total-price.wc-block-components-order-summary-item__total-price{{grid-column:3;text-align:right;white-space:nowrap;}}
.wc-block-checkout__sidebar.wc-block-checkout__sidebar > .wp-block-heading,.wc-block-cart__sidebar.wc-block-cart__sidebar > .wp-block-heading,.wc-block-components-totals-wrapper.wc-block-components-totals-wrapper > .wp-block-heading{{box-sizing:border-box;max-width:100%;border-bottom-color:var(--wp--preset--color--border);}}
body.theme-selvedge .wc-block-components-notice-banner,body.theme-selvedge .woocommerce-message,body.theme-selvedge .woocommerce-error,body.theme-selvedge .woocommerce-info{{background:transparent;border:0;border-top:1px solid var(--wp--preset--color--border);border-bottom:1px solid var(--wp--preset--color--border);border-radius:0;padding:var(--wp--preset--spacing--md) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider,0.08em);text-transform:uppercase;color:var(--wp--preset--color--contrast);}}
body.theme-selvedge .wc-block-components-notice-banner.is-success,body.theme-selvedge .wc-block-components-notice-banner.is-info,body.theme-selvedge .wc-block-components-notice-banner.is-warning,body.theme-selvedge .wc-block-components-notice-banner.is-error,body.theme-selvedge .woocommerce-message,body.theme-selvedge .woocommerce-info,body.theme-selvedge .woocommerce-error{{background:transparent;border-left-width:0;}}
body.theme-selvedge.theme-selvedge .wc-block-components-notice-banner .woocommerce-Button.woocommerce-Button,body.theme-selvedge.theme-selvedge .woocommerce-info .woocommerce-Button.woocommerce-Button,body.theme-selvedge.theme-selvedge .woocommerce-message .woocommerce-Button.woocommerce-Button,body.theme-selvedge.theme-selvedge .woocommerce-error .woocommerce-Button.woocommerce-Button{{background:transparent;color:var(--wp--preset--color--contrast);border:0;text-decoration:underline;text-underline-offset:3px;}}
body.theme-selvedge .wc-block-components-notice-banner.wc-block-components-notice-banner.wc-block-components-notice-banner.wc-block-components-notice-banner.wc-block-components-notice-banner > svg,body.theme-selvedge .wc-block-components-notice-banner.wc-block-components-notice-banner.wc-block-components-notice-banner.wc-block-components-notice-banner__content.wc-block-components-notice-banner__content + svg{{color:var(--wp--preset--color--tertiary);}}
{SENTINEL_CLOSE_PHASE_X}"""


SENTINEL_OPEN_PHASE_W = "/* wc-tells-phase-w-real-bug-cleanup-7 */"
SENTINEL_CLOSE_PHASE_W = "/* /wc-tells-phase-w-real-bug-cleanup-7 */"
CSS_PHASE_W = f"""{SENTINEL_OPEN_PHASE_W}
.wp-block-query-pagination-next.wp-block-query-pagination-next,.wp-block-query-pagination-previous.wp-block-query-pagination-previous,a.wp-block-query-pagination-next.wp-block-query-pagination-next,a.wp-block-query-pagination-previous.wp-block-query-pagination-previous{{display:inline-flex;align-items:center;min-height:32px;padding:6px 12px;}}
.wc-block-components-address-form__address_2-toggle.wc-block-components-address-form__address_2-toggle{{display:inline-flex;align-items:center;min-height:32px;padding:6px 4px;}}
.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button{{display:inline-flex;align-items:center;min-height:32px;padding:6px 0;}}
button.show-password-input.show-password-input{{min-width:32px;min-height:32px;padding:6px;}}
@media (max-width:781px){{header .wp-block-navigation.wp-block-navigation .wp-block-navigation-item__content,header .wp-block-navigation.wp-block-navigation a.wp-block-navigation-item__content,header.wp-block-template-part a,header.wp-block-template-part .wp-block-navigation a,div.wp-block-template-part header a,header[role="banner"] a{{display:inline-flex;align-items:center;min-height:32px;padding-block:6px;}}}}
.wc-block-components-order-summary.wc-block-components-order-summary .wc-block-components-order-summary-item.wc-block-components-order-summary-item{{display:grid;grid-template-columns:auto minmax(0,1fr);min-width:0;}}
.wc-block-components-order-summary.wc-block-components-order-summary .wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description{{min-width:0;max-width:100%;}}
.wc-block-checkout__form.wc-block-checkout__form,.wc-block-checkout__main.wc-block-checkout__main,.wc-block-components-checkout-step.wc-block-components-checkout-step.wc-block-components-checkout-step,.wc-block-components-checkout-step__content.wc-block-components-checkout-step__content.wc-block-components-checkout-step__content,.wc-block-components-address-form-wrapper.wc-block-components-address-form-wrapper.wc-block-components-address-form-wrapper,.wc-block-components-address-address-wrapper.wc-block-components-address-address-wrapper.wc-block-components-address-address-wrapper,.wc-block-components-form.wc-block-components-form #shipping-fields,.wc-block-components-form.wc-block-components-form #billing-fields,.wc-block-components-form.wc-block-components-form #contact-fields,.wc-block-components-form.wc-block-components-form #shipping,.wc-block-components-form.wc-block-components-form #billing,.wc-block-components-form.wc-block-components-form #contact{{min-width:0;max-width:100%;overflow-x:clip;box-sizing:border-box;}}
.wp-block-navigation__responsive-container.wp-block-navigation__responsive-container .wp-block-navigation-item a,.wp-block-navigation__responsive-container.wp-block-navigation__responsive-container a.wp-block-navigation-item__content,.wp-block-navigation__responsive-container.wp-block-navigation__responsive-container a{{display:inline-flex;align-items:center;min-height:32px;padding-block:6px;}}
{SENTINEL_CLOSE_PHASE_W}"""


# wc-tells phase-y: restore the 2-column login grid at desktop.
#
# FAIL MODE WE'RE FIXING
# ----------------------
# Phase T added a blanket `.wo-account-login-grid{grid-template-columns:
# minmax(0,1fr)}` at ALL viewports to stop an overflow bug in a narrow
# context. It also destroyed the intended 2-column login layout on
# desktop: every theme's `/my-account/` logged-out view renders the
# "Welcome back" intro + the sign-in form stacked in a ~220-400px
# centered column on a 1280px viewport, leaving massive whitespace on
# both sides. The Foundry demo's account page pixel-measured at x=348
# to x=576 (228px wide content) out of 1280px — clearly broken.
#
# FIX
# ---
# Keep the mobile single-column (which Phase T correctly established),
# but at min-width:782px restore the designed two-column layout. Each
# theme's `functions.php` opens the grid wrapper around the intro +
# form at logged-out /my-account/, so this selector matches on every
# theme without forking.
#
# Cart/checkout outer widening at >=1280px / >=1600px lives in phase-z
# (same `body` specificity as the inner sidebar-layout rules) so it
# reliably beats `.is-layout-constrained > .alignwide` without fighting
# phase-y for cascade order.
SENTINEL_OPEN_PHASE_Y = "/* wc-tells-phase-y-login-grid-desktop */"
SENTINEL_CLOSE_PHASE_Y = "/* /wc-tells-phase-y-login-grid-desktop */"
CSS_PHASE_Y = f"""{SENTINEL_OPEN_PHASE_Y}
@media (min-width:782px){{.wo-account-login-grid.wo-account-login-grid.wo-account-login-grid{{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--wp--preset--spacing--2-xl);align-items:start;}}}}
{SENTINEL_CLOSE_PHASE_Y}"""


# wc-tells phase-z: finish the WC-chrome fix that phase-y started.
#
# FAIL MODE WE'RE FIXING
# ----------------------
# After phase-y shipped (fix(foundry): 2-column account + wider cart/
# checkout #31) three real user-visible bugs remained on
# demo.regionallyfamous.com -- phase-y was too narrow in scope:
#
# 1. CART/CHECKOUT STILL NARROW AT NORMAL DESKTOP (1280-1599px).
#    Phase-y's widening `@media (min-width:1600px)` and required
#    `.alignwide` class never matched on typical laptop viewports,
#    leaving /cart/ and /checkout/ centred in a ~700-900px column
#    on a 1440px screen. Users on a 13-16" MacBook saw a cramped
#    two-column layout with massive empty gutters.
#
# 2. ORDER-SUMMARY PRODUCT NAMES BROKEN CHARACTER-BY-CHARACTER.
#    Phase-v applied `overflow-wrap:anywhere` to the product-name
#    cells so long SKUs couldn't blow out the mobile layout. That
#    rule does what it says: it breaks at ANY grapheme boundary,
#    including mid-word. Inside the checkout sidebar (~140px for the
#    description column after gutters + image + total), "Bottled
#    Monday Morning" renders as a vertical stack of single-letter
#    rows ("Bott / led / Mond / ay / Morn / ing"). This is the
#    `element-overflow-x` heuristic finding we had allowlisted on
#    checkout-filled across every theme -- a real bug, not a false
#    positive. `break-word` does the right thing instead: it only
#    splits at word boundaries unless a single token is truly wider
#    than the line, preserving word integrity for normal copy.
#
# 3. RETURN-TO-CART BUTTON APPEARS STRIKETHROUGH / INVISIBLE.
#    WC ships the button as an <a>/<button> with a left-pointing
#    chevron SVG + the label "Return to Cart". Without an explicit
#    colour/text-decoration rule, the theme's default link style
#    (often a reset border-bottom or coloured underline) combined
#    with the SVG stroke made it look like a crossed-out, inactive
#    link. We give it an unambiguous colour, a subtle underline
#    that isn't a strikethrough, and a hover tint so it reads as
#    the "back to cart" escape hatch it is.
#
# FIX
# ---
# a. Widen the outer .wp-block-woocommerce-{cart,checkout}.alignwide
#    shell (min-width:1280px -> 1360px, 1600px -> 1440px) AND the inner
#    .wc-block-{cart,checkout}.wc-block-components-sidebar-layout grid
#    so phase-y's login-grid-only scope does not fight cascade order.
# b. Downgrade overflow-wrap from `anywhere` to `break-word` on the
#    order-summary title / description / product-name cells so
#    product names wrap at word boundaries, not mid-glyph. Phase-v's
#    rule stays in place for the rare truly-unbreakable token.
# c. Explicitly style .wc-block-components-checkout-return-to-cart-
#    button with colour + underline-on-hover so it never again
#    renders as a strikethrough ghost.
#
# This block is theme-agnostic -- it targets WC-block selectors only,
# no `body.theme-*` specificity -- so the fix lands identically on
# foundry, obel, chonk, lysholm, selvedge, and aero.
SENTINEL_OPEN_PHASE_Z = "/* wc-tells-phase-z-desktop-wc-chrome-polish */"
SENTINEL_CLOSE_PHASE_Z = "/* /wc-tells-phase-z-desktop-wc-chrome-polish */"
# Phase Z widens the cart/checkout blocks BEYOND wideSize.
#
# Why `body` + two classes: WP's `is-layout-constrained` parent caps
# every child at `var(--wp--style--global--wide-size)` (1440px here) via
#   .is-layout-constrained > .alignwide { max-width: wideSize; }
# which is (0,2,0). WooCommerce 9.x+ renders the cart/checkout grid on
# a single outer div that carries BOTH `wc-block-components-sidebar-layout`
# AND `wc-block-cart` / `wc-block-checkout` (not three repeated
# `.wc-block-cart` tokens). We target that pair under `body` for
# (0,2,1) specificity so the max-width + grid-template-columns wins.
# Margin auto centres the widened block inside its constrained parent.
#
# The sidebar min-width bump (minmax(300px,360px) -> minmax(340px,
# 420px) at >=1280px, minmax(380px,480px) at >=1600px) is what
# actually fixes the order-summary character-stacking: at the stock
# 300-360px sidebar the description grid cell collapses to ~50-90px
# after subtracting padding + image + total-price columns, which
# forces `overflow-wrap:break-word` to mid-word-break "Bottled"
# into "Bott / led". A wider sidebar gives the description cell
# 160-200px, enough for ~18ch of product name per line, so the
# break-word rule only fires on genuinely long single tokens.
CSS_PHASE_Z = f"""{SENTINEL_OPEN_PHASE_Z}
@media (min-width:1280px){{body .wp-block-woocommerce-cart.alignwide,body .wp-block-woocommerce-checkout.alignwide{{max-width:1360px;margin-left:auto;margin-right:auto;}}}}
@media (min-width:1600px){{body .wp-block-woocommerce-cart.alignwide,body .wp-block-woocommerce-checkout.alignwide{{max-width:1440px;}}}}
@media (min-width:1280px){{body .wc-block-cart.wc-block-components-sidebar-layout,body .wc-block-checkout.wc-block-components-sidebar-layout{{max-width:1360px;margin-left:auto;margin-right:auto;}}}}
@media (min-width:1600px){{body .wc-block-cart.wc-block-components-sidebar-layout,body .wc-block-checkout.wc-block-components-sidebar-layout{{max-width:1520px;}}}}
@media (min-width:1280px){{body .wc-block-checkout.wc-block-components-sidebar-layout{{grid-template-columns:minmax(0,1fr) minmax(340px,420px);}} body .wc-block-cart.wc-block-components-sidebar-layout{{grid-template-columns:minmax(0,1fr) minmax(340px,420px);}}}}
@media (min-width:1600px){{body .wc-block-checkout.wc-block-components-sidebar-layout{{grid-template-columns:minmax(0,1fr) minmax(380px,480px);}} body .wc-block-cart.wc-block-components-sidebar-layout{{grid-template-columns:minmax(0,1fr) minmax(380px,480px);}}}}
.wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description,.wc-block-components-order-summary-item__title.wc-block-components-order-summary-item__title.wc-block-components-order-summary-item__title.wc-block-components-order-summary-item__title.wc-block-components-order-summary-item__title,.wc-block-components-product-name.wc-block-components-product-name.wc-block-components-product-name.wc-block-components-product-name.wc-block-components-product-name.wc-block-components-product-name{{overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar.wc-block-checkout__sidebar,.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar.wc-block-cart__sidebar{{overflow-wrap:break-word;word-break:normal;hyphens:none;}}
.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button,.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button:visited{{color:var(--wp--preset--color--contrast);text-decoration:none;border:0;background:transparent;font-weight:var(--wp--custom--font-weight--medium,500);}}
.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button:hover,.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button:focus-visible{{color:var(--wp--preset--color--contrast);text-decoration:underline;text-decoration-color:var(--wp--preset--color--accent,currentColor);text-decoration-thickness:2px;text-underline-offset:3px;}}
.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button>svg{{fill:currentColor;stroke:currentColor;flex:0 0 auto;}}
{SENTINEL_CLOSE_PHASE_Z}"""


# PHASE AA -- RETURN-TO-CART SVG OVERLAP (REAL STRIKETHROUGH BUG).
#
# SYMPTOM
# -------
# On `/checkout/` the "Return to Cart" link at the bottom-left of the
# main column renders as `←Return to Cart` where the left-arrow's
# horizontal shaft cuts through the x-height of the word "Return",
# making the whole link look like it has a `text-decoration:
# line-through`. Users reported it as "the return-to-cart button is
# still messed up" even after phase-z shipped colour + hover styling.
#
# ROOT CAUSE
# ----------
# WooCommerce Blocks' default stylesheet positions the chevron SVG
# absolutely and reserves space for it with padding-left on the anchor:
#
#   .wc-block-components-checkout-return-to-cart-button {
#     padding-left: calc(24px + 0.25em);
#     position: relative;
#   }
#   .wc-block-components-checkout-return-to-cart-button svg {
#     position: absolute;
#     left: 0; top: 50%; transform: translateY(-50%);
#   }
#
# Phases W and X converted the anchor to `display:inline-flex` and
# overrode the shorthand `padding` (0 on the sides, or a small xs on
# the sides). The shorthand kills the 24px+0.25em left padding that
# reserved space for the absolutely-positioned SVG. The SVG is STILL
# `position:absolute; left:0; top:50%; translate(-50%)`, so it draws
# on top of the first letters of the label instead of beside them.
#
# The `flex:0 0 auto; margin-right` phase-X added to the SVG is inert
# as long as the SVG stays out-of-flow (absolute children don't
# participate in flex layout).
#
# FIX
# ---
# Override `position`, `top`, `left`, and `transform` on the SVG so it
# becomes a proper flex child. Combined with phase-X's `margin-right`
# and phase-Z's `>svg { fill; flex }` rules, the arrow renders beside
# the text with an em-sized gap, not across it. No padding-left needed
# -- the flex container sizes itself to (svg + gap + label).
#
# Applies to every theme with zero theme-specific selectors. Idempotent
# because the sentinel guards re-injection.
SENTINEL_OPEN_PHASE_AA = "/* wc-tells-phase-aa-return-to-cart-svg-inflow */"
SENTINEL_CLOSE_PHASE_AA = "/* /wc-tells-phase-aa-return-to-cart-svg-inflow */"
CSS_PHASE_AA = f"""{SENTINEL_OPEN_PHASE_AA}
.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button>svg,.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button>svg.wc-block-components-checkout-return-to-cart-button__svg{{position:static;top:auto;left:auto;transform:none;margin-right:var(--wp--preset--spacing--2-xs,0.25em);}}
.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button.wc-block-components-checkout-return-to-cart-button{{padding-left:var(--wp--preset--spacing--xs,6px);}}
{SENTINEL_CLOSE_PHASE_AA}"""


# Phase BB — universal post-title tap-target floor (issued 2026-04-22).
#
# FAIL MODE WE'RE FIXING
# ----------------------
# `<h*.wp-block-post-title isLink>` renders as a single anchor inside a
# heading. The anchor's hit-box equals its rendered line-box. With a
# fluid `lg` font (1.25rem min on mobile) and a tight editorial
# line-height (e.g. 1.25), single-line titles compute to ~25px tall —
# below the 32px tap-target floor snap.py enforces. Foundry's home
# journal cards regressed exactly this way (3 warnings/run). Other
# themes happen to use looser line-heights, but they're one editorial
# tweak away from the same bug.
#
# Defense in depth: regardless of font-size or line-height, any post-
# title rendered as a link gets `min-height:32px` on mobile via
# inline-flex with vertical centering. The visible text rhythm is
# unchanged; only the anchor's bounding box grows to meet WCAG.
SENTINEL_OPEN_PHASE_BB = "/* wc-tells-phase-bb-post-title-tap-target */"
SENTINEL_CLOSE_PHASE_BB = "/* /wc-tells-phase-bb-post-title-tap-target */"
CSS_PHASE_BB = f"""{SENTINEL_OPEN_PHASE_BB}
@media (max-width:781px){{.wp-block-post-title.wp-block-post-title>a,h1.wp-block-post-title.wp-block-post-title>a,h2.wp-block-post-title.wp-block-post-title>a,h3.wp-block-post-title.wp-block-post-title>a,h4.wp-block-post-title.wp-block-post-title>a,h5.wp-block-post-title.wp-block-post-title>a,h6.wp-block-post-title.wp-block-post-title>a{{display:inline-flex;align-items:center;min-height:32px;}}}}
{SENTINEL_CLOSE_PHASE_BB}"""


# Phase CC — review-form star button tap targets (issued 2026-04-24).
#
# FAIL MODE WE'RE FIXING
# ----------------------
# WooCommerce's modern `woocommerce/product-review-form` block (the one
# we just migrated to after retiring the legacy
# `<!-- wp:woocommerce/product-reviews /-->` self-closing tag) renders
# its star rating control as five `<button role="radio">` elements
# inside a `<p role="radiogroup" class="stars-wrapper">`. The default
# CSS (`assets/client/blocks/woocommerce/product-review-form.css`)
# sizes each star as a 24x24 inline SVG with ~1px horizontal gap — so
# the bounding box is ~26x24 and the whole widget measures a cramped
# ~130x24. On mobile that's below the 32x32 minimum snap.py enforces
# (and below WCAG 2.2 AAA's 44x44 preferred target), and it looks
# undersized next to our editorial typography.
#
# THE FIX
# -------
# On mobile (≤781px — same breakpoint used by Phase BB), inflate each
# star's hit area to 32x32 without resizing the SVG glyph itself:
#   * `inline-flex` + `align-items:center`/`justify-content:center`
#     centres the 24px SVG inside the 32px box.
#   * `min-height:32px` / `min-width:32px` meets snap.py's heuristic
#     and WCAG 2.1 AA (24x24) with margin to spare.
#   * Re-asserting `padding:0` stops any upstream theme defaults from
#     asymmetrically bloating one side of the button.
# Desktop keeps the default 24px glyph size so the stars don't look
# oversized next to the surrounding editorial rhythm.
#
# Specificity: the selector triples `.stars-wrapper` to beat WC Blocks'
# `.wp-block-woocommerce-product-review-form .stars-wrapper button`
# (specificity 0,2,1). Tripled class selector = 0,3,0, which wins.
SENTINEL_OPEN_PHASE_CC = "/* wc-tells-phase-cc-review-star-tap-target */"
SENTINEL_CLOSE_PHASE_CC = "/* /wc-tells-phase-cc-review-star-tap-target */"
CSS_PHASE_CC = f"""{SENTINEL_OPEN_PHASE_CC}
@media (max-width:781px){{.stars-wrapper.stars-wrapper.stars-wrapper button[role="radio"]{{display:inline-flex;align-items:center;justify-content:center;min-width:32px;min-height:32px;padding:0;}}}}
{SENTINEL_CLOSE_PHASE_CC}"""


# Phase DD — give the `woocommerce/product-reviews-title` heading enough
# vertical room that heavy display fonts (chonk at line-height 1.1 +
# font-weight 900 + 4.25rem) don't overflow their own line-box.
#
# The WC block renders as `<h2 class="wp-block-woocommerce-product-reviews-title">`
# without the `wp-block-heading` class, so none of the theme's existing
# `h2.wp-block-heading` rules (phase-V) apply. On chonk, the elements.h2
# default `line-height: var(--custom--line-height--tight, 1.1)` combined
# with the display font's extreme cap-height produces scrollHeight 163
# vs clientHeight 150 on the two-line "0 reviews for …" heading, tripping
# the `heading-clipped-vertical` heuristic.
#
# We raise line-height to 1.3 (doubled class for specificity, matching
# phase-V) only on this specific heading. All other h2s keep their
# designed metrics; this is purely a guard against the WC block's
# unstyled-by-default fall-through.
SENTINEL_OPEN_PHASE_DD = "/* wc-tells-phase-dd-reviews-title-line-height */"
SENTINEL_CLOSE_PHASE_DD = "/* /wc-tells-phase-dd-reviews-title-line-height */"
CSS_PHASE_DD = f"""{SENTINEL_OPEN_PHASE_DD}
.wp-block-woocommerce-product-reviews-title.wp-block-woocommerce-product-reviews-title{{line-height:1.3;}}
{SENTINEL_CLOSE_PHASE_DD}"""


# wc-tells phase-ee: keep `.wo-account-help` full-width inside the
# account login grid across every theme.
#
# FAIL MODE WE'RE FIXING
# ----------------------
# `.wo-account-help` is the "Trouble signing in? …" line rendered by
# `functions.php`'s `// === BEGIN my-account ===` block at priority 20
# on `woocommerce_after_customer_login_form`. That action fires BEFORE
# the grid-closer at priority 25, so the `<p>` lands INSIDE the
# `.wo-account-login-grid` wrapper. Phase Y paints the grid as
# `grid-template-columns: 1fr 1fr` at ≥782px, so without an explicit
# `grid-column: 1 / -1` the help line is auto-placed into a single
# 1fr column (`wo-archive-intro` on the left, login form on the right,
# help text pushed to whichever slot is free -- typically the left
# column under the intro). Cross-theme audit (snap.py report on
# desktop + wide my-account) showed obel + foundry rendered the help
# line at ~556/596px (single column width) while the other four themes
# rendered it at ~1200/1280px (full grid width). That 54-%-drift is
# the `parity-drift-width` warning the cross-theme heuristic fires.
#
# FIX
# ---
# Span the help line across all grid columns unconditionally. This is
# a pure presentational override that doesn't depend on viewport or
# the parent's column count, so `grid-column: 1 / -1` is the minimal
# rule that produces identical layout across every theme. Triple-class
# specificity matches Phase Y's grid-columns override so the fix wins
# the cascade whatever phase-Y ends up emitting.
SENTINEL_OPEN_PHASE_EE = "/* wc-tells-phase-ee-account-help-span */"
SENTINEL_CLOSE_PHASE_EE = "/* /wc-tells-phase-ee-account-help-span */"
CSS_PHASE_EE = f"""{SENTINEL_OPEN_PHASE_EE}
.wo-account-login-grid.wo-account-login-grid.wo-account-login-grid>.wo-account-help{{grid-column:1 / -1;margin-top:var(--wp--preset--spacing--md);}}
{SENTINEL_CLOSE_PHASE_EE}"""


SENTINEL_OPEN_PHASE_V = "/* wc-tells-phase-v-real-bug-cleanup-6 */"
SENTINEL_CLOSE_PHASE_V = "/* /wc-tells-phase-v-real-bug-cleanup-6 */"
CSS_PHASE_V = f"""{SENTINEL_OPEN_PHASE_V}
h1.wp-block-heading.wp-block-heading,h2.wp-block-heading.wp-block-heading,h1.wp-block-post-title.wp-block-post-title,h2.wp-block-post-title.wp-block-post-title{{line-height:1.3;}}
.wp-block-woocommerce-product-template a.wp-block-button__link.wp-block-button__link,.wp-block-woocommerce-product-collection a.wp-block-button__link.wp-block-button__link,.wp-block-woocommerce-product-template .wc-block-components-product-button.wc-block-components-product-button a.wp-block-button__link,.wp-block-woocommerce-product-collection .wc-block-components-product-button.wc-block-components-product-button a.wp-block-button__link{{padding-left:8px;padding-right:8px;min-width:0;max-width:100%;white-space:normal;overflow-wrap:break-word;}}
.wc-block-mini-cart__button.wc-block-mini-cart__button.wc-block-mini-cart__button{{padding-left:6px;padding-right:6px;}}
.wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description.wc-block-components-order-summary-item__description,.wc-block-components-order-summary-item__title.wc-block-components-order-summary-item__title.wc-block-components-order-summary-item__title.wc-block-components-order-summary-item__title,.wc-block-components-product-name.wc-block-components-product-name.wc-block-components-product-name.wc-block-components-product-name.wc-block-components-product-name{{overflow-wrap:anywhere;min-width:0;max-width:100%;}}
{SENTINEL_CLOSE_PHASE_V}"""


# ----------------------------------------------------------------------
# Phase FF — hover foreground polarity auto-flip
# ----------------------------------------------------------------------
# Every `:hover` rule in Phase A–D that paints `{background: var(--accent);
# color: var(--contrast);}` assumes `contrast` has ≥3:1 WCAG against
# `accent`. That's true on obel (4.74:1), chonk (16.57:1), lysholm
# (7.59:1), basalt (5.91:1), selvedge (3.05:1), aero (3.07:1). It is
# NOT true on foundry (`contrast` 2.14:1 on burnt-orange accent) — for
# which a hand-written override lives in Phase E line 732 with doubled
# `.theme-foundry.theme-foundry` specificity — nor on any future theme
# where a mid-luminance `accent` lands close to a mid-luminance
# `contrast`. The cipher smoke on 2026-04-28 reproduced this exactly:
# cream `#E5DFCE` on gold `#C8A04A` = 1.84:1 across 7 WC surfaces
# (mini-cart footer, totals-coupon button, checkout place-order,
# order-confirmation downloads, MyAccount form buttons, orders-table
# buttons, empty-cart primary CTA, footer newsletter submit).
#
# `check_hover_state_legibility` catches this after-the-fact, but the
# remediation (hand-write a `body.theme-<slug>.theme-<slug>` override
# in Phase E) is brittle: every new theme whose palette lands in the
# mid-luminance failure band gets quietly broken until the operator
# notices. Phase FF closes the gap at generation time: read each theme's
# palette once, compute `_wcag_contrast(contrast, accent)` and
# `_wcag_contrast(base, accent)`, and emit an override flip for any
# theme where `contrast`-on-`accent` sits below the 3:1 AA-Large floor
# AND `base`-on-`accent` clears 3:1 (the flip only helps if the
# alternative actually works — otherwise the theme has a fundamentally
# broken accent choice that this script can't paper over).
#
# The output is a per-theme override block:
#
#   body.theme-<slug> <every accent-hover surface>:hover {
#     background: var(--wp--preset--color--accent);
#     color: var(--wp--preset--color--base);
#   }
#
# One `body.theme-<slug>` class chain gives specificity (0,2,N) which
# beats Phase A's (0,1,N) baseline without reaching for `!important`
# (which `check_no_important` blocks outside its curated allowlist).
# The block ships the same CSS to every theme's theme.json — the
# `body.theme-<slug>` selector matches only on that one theme, so
# cipher's rule is dead weight in obel's CSS, obel's rule is dead
# weight in cipher's CSS, etc. Tiny bytes, zero risk of cross-theme
# interference.
#
# Why this block is dynamically composed at script startup instead of
# authored as a static string: the list of "flip-needed themes" is a
# function of each theme's current palette. When a theme's accent
# changes (or a new theme is scaffolded with a mid-luminance accent),
# running `bin/append-wc-overrides.py --update` recomputes the block
# from current `theme.json` values and rewrites the sentinel contents
# everywhere. Pre-push's drift check (root-rule #19) will catch anyone
# who edits a palette without rerunning the script.
#
# Related: `bin/check.py::check_hover_state_legibility` is the hard
# gate; this phase is the remediation. The two pieces together mean a
# palette change that produces a mid-luminance accent gets auto-flipped
# to legibility without any manual Phase E work.

# The 12 Woo+theme surfaces where Phase A–D hover rules paint
# `{background:accent; color:contrast}`. Kept in sync (manually) with
# the rule list in Phase A–D; if a future phase adds another accent-
# hover surface, add its selector here so the flip reaches it. This is
# a one-line grep against `append-wc-overrides.py` looking for
# `:hover` selectors that set `background:var(--wp--preset--color--
# accent)` and `color:var(--wp--preset--color--contrast)` together.
_HOVER_ACCENT_SURFACES: tuple[str, ...] = (
    ".wc-block-mini-cart__footer-actions a",
    ".wc-block-mini-cart__footer-actions .wc-block-components-button",
    ".wc-block-components-totals-coupon__button",
    ".wc-block-components-totals-coupon button",
    ".wc-block-cart__submit-container .wc-block-components-checkout-place-order-button",
    ".wc-block-cart__submit-container a.wc-block-cart__submit-button",
    ".wc-block-components-checkout-place-order-button",
    ".wp-block-woocommerce-order-confirmation-downloads .button",
    ".woocommerce-MyAccount-content form .button",
    ".woocommerce-orders-table .button",
    ".wo-empty__cta--primary",
    ".selvedge-footer__newsletter-submit",
)


def _wcag_luminance_hex(hex_color: str) -> float | None:
    """WCAG 2.x relative luminance for `#RRGGBB`. Returns `None` on
    unparseable input — the caller treats that as "skip this theme"
    rather than crashing mid-generation.

    Duplicated in `bin/check.py::_wcag_luminance` and
    `bin/design.py::_wcag_luminance_hex`. Keeping three copies rather
    than an import because each script must stay runnable in isolation
    (no cyclic import risk, no shared module to bootstrap). When one
    changes, update all three — the drift check will fire if they
    disagree on any theme's classification."""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _wcag_contrast_hex(a: str, b: str) -> float | None:
    """WCAG 2.x contrast ratio between two `#RRGGBB` hex strings.
    Returns `None` if either is unparseable."""
    la = _wcag_luminance_hex(a)
    lb = _wcag_luminance_hex(b)
    if la is None or lb is None:
        return None
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _read_palette(slug: str) -> dict[str, str]:
    """Return `{slug: hex}` for one theme's palette, or `{}` if the
    theme.json is missing / malformed. Swallows IOError + JSONDecodeError
    on purpose — a corrupt theme.json is a separate problem with its
    own check (`check_json_validity`); Phase FF shouldn't crash the
    entire append pipeline for it."""
    import json

    try:
        data = json.loads(
            (ROOT / slug / "theme.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    palette = data.get("settings", {}).get("color", {}).get("palette", [])
    return {
        e["slug"]: e["color"]
        for e in palette
        if isinstance(e, dict) and "slug" in e and "color" in e
    }


def _hover_accent_flip_themes() -> list[str]:
    """Return slugs whose `contrast`-on-`accent` contrast fails the 3:1
    floor AND whose `base`-on-`accent` clears it. Runs once at script
    startup over `discover_themes(stages=())` so every on-disk theme
    (shipping, incubating, or retired) is considered — the resulting
    override block is cheap dead-weight on themes that don't match it,
    but it would silently leave cipher broken if we scoped the scan
    to shipping-only."""
    flips: list[str] = []
    for slug in discover_themes(stages=()):
        palette = _read_palette(slug)
        base = palette.get("base")
        contrast = palette.get("contrast")
        accent = palette.get("accent")
        if not (base and contrast and accent):
            continue
        c_on_a = _wcag_contrast_hex(contrast, accent)
        b_on_a = _wcag_contrast_hex(base, accent)
        if c_on_a is None or b_on_a is None:
            continue
        if c_on_a < 3.0 and b_on_a >= 3.0:
            flips.append(slug)
    return flips


_HOVER_ACCENT_FLIP_THEMES: tuple[str, ...] = tuple(_hover_accent_flip_themes())


def _build_phase_ff_css() -> str:
    """Assemble Phase FF's CSS. One selector-group rule per flip theme;
    empty body (just the sentinels) when no theme needs the flip so
    the sentinel pair is still present and the chunk is still
    idempotent."""
    rule_parts: list[str] = []
    for slug in _HOVER_ACCENT_FLIP_THEMES:
        # `body.theme-<slug>.theme-<slug>` doubled-class trick on every
        # surface, joined with commas — bumps specificity from (0,3,2)
        # to (0,4,2), which is what `check_wc_overrides_styled` requires
        # for overrides to win the cascade against WC Blocks baselines
        # like `.wp-block-woocommerce-product-details ul.wc-tabs li
        # a:hover` at (0,3,3). Matches the exact shape of the Phase E
        # hand-written foundry override on line 732.
        group = ",".join(
            f"body.theme-{slug}.theme-{slug} {surface}:hover"
            for surface in _HOVER_ACCENT_SURFACES
        )
        rule_parts.append(
            f"{group}{{background:var(--wp--preset--color--accent);"
            f"color:var(--wp--preset--color--base);}}"
        )
    body = "".join(rule_parts)
    return (
        f"{SENTINEL_OPEN_PHASE_FF}\n"
        f"{body}\n"
        f"{SENTINEL_CLOSE_PHASE_FF}"
    )


SENTINEL_OPEN_PHASE_FF = "/* wc-tells-phase-ff-hover-polarity-autoflip */"
SENTINEL_CLOSE_PHASE_FF = "/* /wc-tells-phase-ff-hover-polarity-autoflip */"
CSS_PHASE_FF = _build_phase_ff_css()


# ----------------------------------------------------------------------
# Phase GG — universal header flex-wrap on tablet+mobile
# ----------------------------------------------------------------------
# Phase T shipped `@media (max-width:781px) { body.theme-selvedge ...
# body.theme-chonk ... body.theme-lysholm ... { flex-wrap:wrap; } }` —
# a hard-enumerated list of themes whose primary nav overflowed the
# alignwide column at tablet (768px). Every other theme was trusted to
# fit. Cipher's smoke on 2026-04-28 showed the enumeration is brittle:
# a 6-char brand name + 6-item nav + 3-icon utility bar overflowed the
# 705px alignwide by 14-20px at tablet. Same fix selvedge/chonk/lysholm
# already had, but the enumeration didn't include cipher (or any future
# theme).
#
# The fix is universal: `flex-wrap:wrap` on the header's alignfull /
# alignwide containers is a no-op for themes whose content already fits
# (flex-wrap is allowed-to-wrap, not required-to-wrap), so applying it
# to every theme costs nothing and closes the enumeration footgun.
#
# Phase T's rule set is RETIRED here rather than deleted — Phase T's
# sentinel body now contains a comment explaining the replacement.
# Deleting the sentinel outright would leave Phase U's anchor
# (SENTINEL_CLOSE_PHASE_T) dangling.
SENTINEL_OPEN_PHASE_GG = "/* wc-tells-phase-gg-header-wrap-universal */"
SENTINEL_CLOSE_PHASE_GG = "/* /wc-tells-phase-gg-header-wrap-universal */"
CSS_PHASE_GG = f"""{SENTINEL_OPEN_PHASE_GG}
@media (max-width:781px){{.wp-site-blocks header.wp-block-group.alignfull.alignfull,.wp-site-blocks header.wp-block-group.alignfull .wp-block-group.alignfull,.wp-site-blocks header.wp-block-group.alignfull .wp-block-group.alignwide{{flex-wrap:wrap;min-width:0;max-width:100%;}}.wp-site-blocks header.wp-block-group.alignfull .wp-block-navigation,.wp-site-blocks header.wp-block-group.alignfull .wp-block-navigation__container{{flex-wrap:wrap;min-width:0;max-width:100%;}}}}
body.woocommerce-account.woocommerce-account .entry-content>.woocommerce:has(>.woocommerce-MyAccount-navigation){{display:grid;grid-template-columns:minmax(160px,180px) minmax(0,1fr);gap:var(--wp--preset--spacing--xl);align-items:start;width:100%;max-width:100%;box-sizing:border-box;}}
@media (max-width:781px){{body.woocommerce-account.woocommerce-account .entry-content>.woocommerce:has(>.woocommerce-MyAccount-navigation){{grid-template-columns:minmax(0,1fr);gap:var(--wp--preset--spacing--lg);}}}}
{SENTINEL_CLOSE_PHASE_GG}"""


# Each entry: (sentinel_open, sentinel_close, raw_css, anchor_after).
# `anchor_after` is the marker the chunk is spliced in after — for the
# first chunk that's the canonical archive-page marker; for follow-ups
# it's the previous chunk's close sentinel so chunks land in a stable
# documented order.
CHUNKS: list[tuple[str, str, str, str]] = [
    (
        SENTINEL_OPEN,
        SENTINEL_CLOSE,
        CSS,
        "/* /archive-product polish */",
    ),
    (
        SENTINEL_OPEN_CART_FIX,
        SENTINEL_CLOSE_CART_FIX,
        CSS_CART_FIX,
        SENTINEL_CLOSE,
    ),
    (
        SENTINEL_OPEN_CO_FIX,
        SENTINEL_CLOSE_CO_FIX,
        CSS_CO_FIX,
        SENTINEL_CLOSE_CART_FIX,
    ),
    (
        SENTINEL_OPEN_GRID_FIX,
        SENTINEL_CLOSE_GRID_FIX,
        CSS_GRID_FIX,
        SENTINEL_CLOSE_CO_FIX,
    ),
    (
        SENTINEL_OPEN_CO_OUTER,
        SENTINEL_CLOSE_CO_OUTER,
        CSS_CO_OUTER,
        SENTINEL_CLOSE_GRID_FIX,
    ),
    (
        SENTINEL_OPEN_PHASE_A,
        SENTINEL_CLOSE_PHASE_A,
        CSS_PHASE_A,
        SENTINEL_CLOSE_CO_OUTER,
    ),
    (
        SENTINEL_OPEN_PHASE_B,
        SENTINEL_CLOSE_PHASE_B,
        CSS_PHASE_B,
        SENTINEL_CLOSE_PHASE_A,
    ),
    (
        SENTINEL_OPEN_PHASE_C,
        SENTINEL_CLOSE_PHASE_C,
        CSS_PHASE_C,
        SENTINEL_CLOSE_PHASE_B,
    ),
    (
        SENTINEL_OPEN_PHASE_D,
        SENTINEL_CLOSE_PHASE_D,
        CSS_PHASE_D,
        SENTINEL_CLOSE_PHASE_C,
    ),
    (
        SENTINEL_OPEN_PHASE_D_FOOTER,
        SENTINEL_CLOSE_PHASE_D_FOOTER,
        CSS_PHASE_D_FOOTER,
        SENTINEL_CLOSE_PHASE_D,
    ),
    (
        SENTINEL_OPEN_PHASE_E,
        SENTINEL_CLOSE_PHASE_E,
        CSS_PHASE_E,
        SENTINEL_CLOSE_PHASE_D_FOOTER,
    ),
    (
        SENTINEL_OPEN_PHASE_F,
        SENTINEL_CLOSE_PHASE_F,
        CSS_PHASE_F,
        SENTINEL_CLOSE_PHASE_E,
    ),
    (
        SENTINEL_OPEN_PHASE_G,
        SENTINEL_CLOSE_PHASE_G,
        CSS_PHASE_G,
        SENTINEL_CLOSE_PHASE_F,
    ),
    (
        SENTINEL_OPEN_PHASE_H,
        SENTINEL_CLOSE_PHASE_H,
        CSS_PHASE_H,
        SENTINEL_CLOSE_PHASE_G,
    ),
    (
        SENTINEL_OPEN_PHASE_I,
        SENTINEL_CLOSE_PHASE_I,
        CSS_PHASE_I,
        SENTINEL_CLOSE_PHASE_H,
    ),
    (
        SENTINEL_OPEN_PHASE_J,
        SENTINEL_CLOSE_PHASE_J,
        CSS_PHASE_J,
        SENTINEL_CLOSE_PHASE_I,
    ),
    (
        SENTINEL_OPEN_PHASE_K,
        SENTINEL_CLOSE_PHASE_K,
        CSS_PHASE_K,
        SENTINEL_CLOSE_PHASE_J,
    ),
    (
        SENTINEL_OPEN_PHASE_L,
        SENTINEL_CLOSE_PHASE_L,
        CSS_PHASE_L,
        SENTINEL_CLOSE_PHASE_K,
    ),
    (
        SENTINEL_OPEN_PHASE_M,
        SENTINEL_CLOSE_PHASE_M,
        CSS_PHASE_M,
        SENTINEL_CLOSE_PHASE_L,
    ),
    (
        SENTINEL_OPEN_PHASE_N,
        SENTINEL_CLOSE_PHASE_N,
        CSS_PHASE_N,
        SENTINEL_CLOSE_PHASE_M,
    ),
    (
        SENTINEL_OPEN_PHASE_O,
        SENTINEL_CLOSE_PHASE_O,
        CSS_PHASE_O,
        SENTINEL_CLOSE_PHASE_N,
    ),
    (
        SENTINEL_OPEN_PHASE_P,
        SENTINEL_CLOSE_PHASE_P,
        CSS_PHASE_P,
        SENTINEL_CLOSE_PHASE_O,
    ),
    (
        SENTINEL_OPEN_PHASE_Q,
        SENTINEL_CLOSE_PHASE_Q,
        CSS_PHASE_Q,
        SENTINEL_CLOSE_PHASE_P,
    ),
    (
        SENTINEL_OPEN_PHASE_R,
        SENTINEL_CLOSE_PHASE_R,
        CSS_PHASE_R,
        SENTINEL_CLOSE_PHASE_Q,
    ),
    (
        SENTINEL_OPEN_PHASE_S,
        SENTINEL_CLOSE_PHASE_S,
        CSS_PHASE_S,
        SENTINEL_CLOSE_PHASE_R,
    ),
    (
        SENTINEL_OPEN_PHASE_T,
        SENTINEL_CLOSE_PHASE_T,
        CSS_PHASE_T,
        SENTINEL_CLOSE_PHASE_S,
    ),
    (
        SENTINEL_OPEN_PHASE_U,
        SENTINEL_CLOSE_PHASE_U,
        CSS_PHASE_U,
        SENTINEL_CLOSE_PHASE_T,
    ),
    (
        SENTINEL_OPEN_PHASE_V,
        SENTINEL_CLOSE_PHASE_V,
        CSS_PHASE_V,
        SENTINEL_CLOSE_PHASE_U,
    ),
    (
        SENTINEL_OPEN_PHASE_W,
        SENTINEL_CLOSE_PHASE_W,
        CSS_PHASE_W,
        SENTINEL_CLOSE_PHASE_V,
    ),
    (
        SENTINEL_OPEN_PHASE_X,
        SENTINEL_CLOSE_PHASE_X,
        CSS_PHASE_X,
        SENTINEL_CLOSE_PHASE_W,
    ),
    (
        SENTINEL_OPEN_PHASE_Y,
        SENTINEL_CLOSE_PHASE_Y,
        CSS_PHASE_Y,
        SENTINEL_CLOSE_PHASE_X,
    ),
    (
        SENTINEL_OPEN_PHASE_Z,
        SENTINEL_CLOSE_PHASE_Z,
        CSS_PHASE_Z,
        SENTINEL_CLOSE_PHASE_Y,
    ),
    (
        SENTINEL_OPEN_PHASE_AA,
        SENTINEL_CLOSE_PHASE_AA,
        CSS_PHASE_AA,
        SENTINEL_CLOSE_PHASE_Z,
    ),
    (
        SENTINEL_OPEN_PHASE_BB,
        SENTINEL_CLOSE_PHASE_BB,
        CSS_PHASE_BB,
        SENTINEL_CLOSE_PHASE_AA,
    ),
    (
        SENTINEL_OPEN_PHASE_CC,
        SENTINEL_CLOSE_PHASE_CC,
        CSS_PHASE_CC,
        SENTINEL_CLOSE_PHASE_BB,
    ),
    (
        SENTINEL_OPEN_PHASE_DD,
        SENTINEL_CLOSE_PHASE_DD,
        CSS_PHASE_DD,
        SENTINEL_CLOSE_PHASE_CC,
    ),
    (
        SENTINEL_OPEN_PHASE_EE,
        SENTINEL_CLOSE_PHASE_EE,
        CSS_PHASE_EE,
        SENTINEL_CLOSE_PHASE_DD,
    ),
    (
        SENTINEL_OPEN_PHASE_FF,
        SENTINEL_CLOSE_PHASE_FF,
        CSS_PHASE_FF,
        SENTINEL_CLOSE_PHASE_EE,
    ),
    (
        SENTINEL_OPEN_PHASE_GG,
        SENTINEL_CLOSE_PHASE_GG,
        CSS_PHASE_GG,
        SENTINEL_CLOSE_PHASE_FF,
    ),
]


def _flatten(css: str) -> str:
    """Collapse our authored CSS to one line, matching the existing
    minified style of the surrounding styles.css value."""
    return " ".join(line.strip() for line in css.splitlines() if line.strip())


def _json_escape(s: str) -> str:
    """JSON-string-escape a CSS chunk. Only backslash and double quote
    need escaping for our CSS (no control chars; the chevron SVG uses
    single quotes internally)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _splice_after(text: str, anchor: str, payload: str) -> tuple[str, str]:
    """Insert `payload` immediately after the first occurrence of `anchor`
    inside `text`. Returns (new_text, status_message). If anchor is missing
    or non-unique we return text unchanged so a typo can't silently pad
    the file with duplicate or misplaced content."""
    if text.count(anchor) != 1:
        return text, f"anchor {anchor!r} missing or non-unique"
    idx = text.index(anchor) + len(anchor)
    return text[:idx] + payload + text[idx:], "ok"


def append_for(theme: str, *, update: bool = False) -> str:
    """Walk every chunk in CHUNKS for one theme. Default behavior:
    skip chunks whose open-sentinel is already present so re-runs are
    no-ops. If `update=True`, replace the body between the existing
    sentinels with the current source so edits to CSS chunks
    propagate to every theme.json."""
    path = ROOT / theme / "theme.json"
    text = path.read_text(encoding="utf-8")
    notes: list[str] = []
    for sentinel_open, sentinel_close, css, anchor in CHUNKS:
        flat = _flatten(css)
        escaped = _json_escape(flat)
        if sentinel_open in text:
            if not update:
                notes.append(f"skip {sentinel_open}")
                continue
            open_idx = text.find(sentinel_open)
            close_idx = text.find(sentinel_close, open_idx)
            if close_idx == -1:
                notes.append(f"FAIL {sentinel_open}: close sentinel missing")
                continue
            close_end = close_idx + len(sentinel_close)
            text = text[:open_idx] + escaped + text[close_end:]
            notes.append(f"~{len(flat)} {sentinel_open}")
            continue
        text, status = _splice_after(text, anchor, escaped)
        if status != "ok":
            notes.append(f"FAIL {sentinel_open}: {status}")
            continue
        notes.append(f"+{len(flat)} {sentinel_open}")
    path.write_text(text, encoding="utf-8")
    return f"{theme}: " + "; ".join(notes)


def main(argv: list[str]) -> int:
    import argparse
    import subprocess

    parser = argparse.ArgumentParser(
        description="Append WC override CSS chunks to each theme's "
                    "theme.json. Idempotent."
    )
    parser.add_argument(
        "themes", nargs="*",
        help=f"Theme slugs to update. Default: {', '.join(THEMES)}.",
    )
    parser.add_argument(
        "--snap",
        action="store_true",
        help=(
            "After appending, run `bin/snap.py check --changed` so the "
            "tiered gate validates that the new CSS rules didn't "
            "regress any cell. This script ALWAYS changes rendered "
            "output, so --snap is the recommended follow-up."
        ),
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "Replace the body between existing sentinels with the "
            "current source CSS. Use this when you've edited a chunk "
            "in this script and want the changes to land in every "
            "theme.json without manually deleting the old block."
        ),
    )
    args = parser.parse_args(argv[1:])

    targets = args.themes or THEMES
    # Accept any slug with a real theme.json + playground/blueprint.json
    # on disk, even if it's incubating (and therefore hidden from the
    # default shipping-only `THEMES` list). The script's guard was
    # originally about typo-catching for the no-argument default run;
    # when a slug is passed explicitly, the operator knows what they're
    # asking for. This is needed so `design.py build <incubating-slug>`
    # can pipe the new theme through `append-wc-overrides.py <slug>`
    # and pick up auto-generated phases (FF hover flip, GG nav wrap)
    # without the operator having to flip the readiness stage first.
    all_on_disk = frozenset(discover_themes(stages=()))
    appended_any = False
    for t in targets:
        if t not in all_on_disk:
            print(f"unknown theme: {t}", file=sys.stderr)
            return 2
        result = append_for(t, update=args.update)
        print(result)
        # If anything other than 'skip' notes appeared, we mutated the
        # theme.json -- worth running snap.
        if "+" in result or "~" in result or "FAIL" in result:
            appended_any = True

    if appended_any:
        print(
            "\n>> Recommended: python3 bin/snap.py check --changed\n"
            "   (CSS rules just changed; re-shoot the affected themes\n"
            "   and run the tiered gate.)"
        )

    if args.snap and appended_any:
        snap_path = Path(__file__).resolve().parent / "snap.py"
        cmd = [sys.executable, str(snap_path), "check", "--changed"]
        print(f"\n>> {' '.join(cmd[1:])}")
        rc = subprocess.call(
            cmd, cwd=str(Path(__file__).resolve().parent.parent)
        )
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
