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

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = ["obel", "chonk", "selvedge", "lysholm", "aero"]

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
.added_to_cart:hover{{color:var(--wp--preset--color--accent);}}
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
.wc-block-mini-cart__footer-actions a:hover,.wc-block-mini-cart__footer-actions .wc-block-components-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.wp-block-woocommerce-empty-mini-cart-contents-block{{text-align:center;font-family:var(--wp--preset--font-family--sans);}}
.wc-block-cart{{display:grid;grid-template-columns:1fr;gap:var(--wp--preset--spacing--2-xl);}}
@media (min-width:782px){{.wc-block-cart{{grid-template-columns:minmax(0,1fr) minmax(300px,360px);}}}}
.wc-block-cart-items,.wp-block-woocommerce-cart-line-items-block{{padding:0;margin:0;border-collapse:collapse;border:0;}}
.wc-block-cart-items th{{display:none;}}
.wc-block-cart-items .wc-block-cart-items__row{{display:grid;grid-template-columns:96px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--md) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-cart-item__image img{{display:block;width:96px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-cart-item__product .wc-block-components-product-name{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--md);font-weight:var(--wp--custom--font-weight--regular);color:var(--wp--preset--color--contrast);text-decoration:none;}}
.wc-block-cart-item__product .wc-block-components-product-name:hover{{color:var(--wp--preset--color--accent);}}
.wc-block-cart-item__product .wc-block-components-product-metadata{{font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);margin-top:var(--wp--preset--spacing--2-xs);}}
.wc-block-cart-item__total{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);text-align:right;}}
.wc-block-components-quantity-selector{{display:inline-flex;align-items:stretch;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--pill);overflow:hidden;background:var(--wp--preset--color--surface);}}
.wc-block-components-quantity-selector__input{{width:48px;border:0;background:transparent;text-align:center;font-family:inherit;font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);appearance:textfield;-moz-appearance:textfield;}}
.wc-block-components-quantity-selector__input::-webkit-inner-spin-button,.wc-block-components-quantity-selector__input::-webkit-outer-spin-button{{-webkit-appearance:none;margin:0;}}
.wc-block-components-quantity-selector__button{{background:transparent;border:0;color:var(--wp--preset--color--contrast);width:32px;cursor:pointer;font-size:var(--wp--preset--font-size--base);transition:color 160ms ease;}}
.wc-block-components-quantity-selector__button:hover{{color:var(--wp--preset--color--accent);}}
.wc-block-cart__sidebar{{padding:var(--wp--preset--spacing--lg);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);}}
.wc-block-components-totals-item{{display:flex;justify-content:space-between;align-items:baseline;padding:var(--wp--preset--spacing--xs) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.wc-block-components-totals-item__label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wc-block-components-totals-footer-item{{border-top:1px solid var(--wp--preset--color--border);padding-top:var(--wp--preset--spacing--md);margin-top:var(--wp--preset--spacing--xs);}}
.wc-block-components-totals-footer-item .wc-block-components-totals-item__value{{font-size:var(--wp--preset--font-size--lg);font-weight:var(--wp--custom--font-weight--medium);}}
.wc-block-components-totals-coupon__form{{display:flex;gap:var(--wp--preset--spacing--xs);}}
.wc-block-components-totals-coupon__input,.wc-block-components-totals-coupon input[type=text]{{flex:1;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
.wc-block-components-totals-coupon__button,.wc-block-components-totals-coupon button{{background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--lg);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;cursor:pointer;transition:background 160ms ease;}}
.wc-block-components-totals-coupon__button:hover,.wc-block-components-totals-coupon button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.wc-block-cart__submit-container .wc-block-components-checkout-place-order-button,.wc-block-cart__submit-container a.wc-block-cart__submit-button{{display:inline-flex;align-items:center;justify-content:center;width:100%;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wide);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--xl);text-decoration:none;cursor:pointer;transition:background 160ms ease,transform 160ms ease;}}
.wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover,.wc-block-cart__submit-container a.wc-block-cart__submit-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);transform:translateY(-1px);}}
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
.wc-block-checkout__login-prompt:hover,.wc-block-checkout__contact-information .wc-block-components-checkout-step__heading-content a:hover{{color:var(--wp--preset--color--accent);}}
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
.wc-block-components-checkout-place-order-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);transform:translateY(-1px);}}
.wc-block-components-order-summary{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);}}
.wc-block-components-order-summary-item{{display:grid;grid-template-columns:64px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--sm) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-components-order-summary-item__image img{{display:block;width:64px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-components-order-summary-item__description{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.wc-block-components-order-summary-item__quantity{{position:static;background:transparent;color:var(--wp--preset--color--secondary);font-size:var(--wp--preset--font-size--xs);width:auto;height:auto;border:0;}}
.wp-block-woocommerce-order-confirmation-downloads table{{width:100%;border-collapse:collapse;font-size:var(--wp--preset--font-size--sm);}}
.wp-block-woocommerce-order-confirmation-downloads th,.wp-block-woocommerce-order-confirmation-downloads td{{padding:var(--wp--preset--spacing--md);border-bottom:1px solid var(--wp--preset--color--border);text-align:left;vertical-align:top;}}
.wp-block-woocommerce-order-confirmation-downloads thead th{{background:var(--wp--preset--color--subtle);font-weight:var(--wp--custom--font-weight--semibold);text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider);font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);}}
.wp-block-woocommerce-order-confirmation-downloads .button{{display:inline-flex;align-items:center;justify-content:center;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--xs) var(--wp--preset--spacing--md);text-decoration:none;transition:background 160ms ease;}}
.wp-block-woocommerce-order-confirmation-downloads .button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.wp-block-woocommerce-order-confirmation-create-account form{{display:grid;gap:var(--wp--preset--spacing--md);padding:var(--wp--preset--spacing--lg);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);}}
.wp-block-woocommerce-order-confirmation-create-account label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wp-block-woocommerce-order-confirmation-create-account input[type=password],.wp-block-woocommerce-order-confirmation-create-account input[type=text]{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
.wp-block-woocommerce-order-confirmation-create-account input[type=submit],.wp-block-woocommerce-order-confirmation-create-account button[type=submit]{{background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--lg);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;cursor:pointer;}}
.woocommerce-account .woocommerce{{display:grid;grid-template-columns:220px 1fr;gap:var(--wp--preset--spacing--2-xl);}}
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
.woocommerce-MyAccount-content form .button:hover,.woocommerce-orders-table .button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.woocommerce-EditAccountForm,.woocommerce-address-fields__field-wrapper{{display:grid;gap:var(--wp--preset--spacing--md);}}
.woocommerce-EditAccountForm label,.woocommerce-address-fields__field-wrapper label{{display:block;font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin-bottom:var(--wp--preset--spacing--2-xs);}}
.woocommerce-EditAccountForm input,.woocommerce-address-fields__field-wrapper input,.woocommerce-EditAccountForm select,.woocommerce-address-fields__field-wrapper select{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
@media (max-width:720px){{.woocommerce-account .woocommerce{{grid-template-columns:1fr;}}}}
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
#   4. Suppress lingering loading skeletons. WC Blocks renders skeleton
#      placeholders during hydration; on slow first-loads the skeleton
#      can persist visibly long enough to look like the page is broken.
#      Hide the skeleton entirely on the frontend (the real content
#      replaces it ~50ms later anyway).
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
.wc-block-components-skeleton,.wp-block-woocommerce-checkout .wc-block-components-skeleton,.wc-block-components-loading-mask,.wc-block-components-skeleton__element{{display:none!important;}}
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
#                             wo-payment-icons-mu.php injects below the
#                             Place Order button on cart + checkout.
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
# Pairs with the page-level injections in wo-pages-mu.php and the new
# templates in <theme>/templates/{order-confirmation,404}.html. Each
# block here is keyed to a CSS class produced by the mu-plugin or the
# template, never relies on WC core selectors that might change shape.
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
.wo-empty__cta--primary:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);color:var(--wp--preset--color--base);}}
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
.chonk-footer__wordmark .wp-block-site-title a:hover{{color:var(--wp--preset--color--accent);}}
.selvedge-footer__newsletter-form{{display:grid;grid-template-columns:1fr auto;gap:0;align-items:stretch;max-width:480px;margin:var(--wp--preset--spacing--md) auto 0;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--sm,4px);overflow:hidden;background:var(--wp--preset--color--base);}}
.selvedge-footer__newsletter-label{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}}
.selvedge-footer__newsletter-input{{border:0;background:transparent;padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);min-width:0;}}
.selvedge-footer__newsletter-input:focus{{outline:none;}}
.selvedge-footer__newsletter-submit{{border:0;border-left:1px solid var(--wp--preset--color--border);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;padding:0 var(--wp--preset--spacing--lg);cursor:pointer;transition:background 160ms ease;}}
.selvedge-footer__newsletter-submit:hover{{background:var(--wp--preset--color--accent);}}
{SENTINEL_CLOSE_PHASE_D_FOOTER}"""


# ---------------------------------------------------------------------------
# Phase E: per-theme distinctive polish.
# ---------------------------------------------------------------------------
# Scoped via the `body.theme-<slug>` class injected by wo-pages-mu.php.
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
body.theme-lysholm .wc-block-cart__sidebar{{background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--accent-soft,var(--wp--preset--color--border));border-radius:var(--wp--custom--radius--lg,16px);box-shadow:0 2px 12px rgba(0,0,0,0.04);}}
body.theme-chonk .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--base);border:4px solid var(--wp--preset--color--contrast);border-radius:0;box-shadow:8px 8px 0 var(--wp--preset--color--contrast);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-obel .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-selvedge .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:0;display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
body.theme-lysholm .wc-block-checkout__sidebar{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--accent-soft,var(--wp--preset--color--border));border-radius:var(--wp--custom--radius--lg,16px);box-shadow:0 2px 12px rgba(0,0,0,0.04);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--lg);}}
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
body .wc-block-components-text-input,body .wc-block-components-text-input input,body .wc-block-components-select,body .wc-block-components-select select,body .wc-block-components-textarea,body .wc-block-components-textarea textarea{{background:var(--wp--preset--color--surface);color:var(--wp--preset--color--contrast);}}
body .wc-block-components-text-input label,body .wc-block-components-select label,body .wc-blocks-components-select__label,body .wc-block-components-textarea label{{color:var(--wp--preset--color--secondary);}}
body .wc-block-components-text-input input::placeholder,body .wc-block-components-textarea textarea::placeholder{{color:var(--wp--preset--color--secondary);opacity:1;}}
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
body.theme-aero .wp-block-site-title a,body.theme-aero .wp-block-site-title{{background:linear-gradient(180deg,var(--wp--preset--color--surface) 0%,var(--wp--preset--color--muted) 30%,var(--wp--preset--color--tertiary) 50%,var(--wp--preset--color--muted) 70%,var(--wp--preset--color--surface) 100%);-webkit-background-clip:text;background-clip:text;color:transparent !important;text-shadow:0 1px 0 rgba(255,255,255,0.6);font-family:var(--wp--preset--font-family--display) !important;letter-spacing:0.02em !important;}}
body.theme-aero .wp-block-site-title a:hover{{background:linear-gradient(180deg,var(--wp--preset--color--surface) 0%,var(--wp--preset--color--iridescent) 30%,var(--wp--preset--color--accent) 50%,var(--wp--preset--color--iridescent) 70%,var(--wp--preset--color--surface) 100%);-webkit-background-clip:text;background-clip:text;color:transparent !important;}}
body.theme-aero .wc-block-product-template>li,body.theme-aero .wc-block-product-collection .wp-block-post,body.theme-aero .products li.product,body.theme-aero .wp-block-product{{position:relative;background:rgba(255,255,255,0.55);border:1px solid rgba(255,255,255,0.75);border-radius:var(--wp--custom--radius--xl,36px);padding:var(--wp--preset--spacing--md);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);box-shadow:inset 0 1px 0 rgba(255,255,255,0.9),0 12px 28px rgba(74,63,135,0.14);overflow:hidden;}}
body.theme-aero .wc-block-product-template>li::after,body.theme-aero .wc-block-product-collection .wp-block-post::after,body.theme-aero .products li.product::after,body.theme-aero .wp-block-product::after{{content:"\\2728";position:absolute;top:10px;right:14px;font-size:14px;line-height:1;opacity:0.7;pointer-events:none;filter:drop-shadow(0 1px 0 rgba(255,255,255,0.8));}}
body.theme-aero .wc-block-product-template>li img,body.theme-aero .wc-block-product-collection .wp-block-post img,body.theme-aero .products li.product img,body.theme-aero .wp-block-product img{{border-radius:var(--wp--custom--radius--lg,24px);}}
body.theme-aero .onsale,body.theme-aero span.onsale,body.theme-aero .wc-block-product-collection .wc-block-components-product-sale-badge{{background:linear-gradient(135deg,var(--wp--preset--color--iridescent) 0%,var(--wp--preset--color--accent-soft) 50%,var(--wp--preset--color--muted) 100%) !important;color:var(--wp--preset--color--contrast) !important;border:1px solid rgba(255,255,255,0.8) !important;border-radius:var(--wp--custom--radius--pill,9999px) !important;padding:6px 14px !important;font-family:var(--wp--preset--font-family--display) !important;text-transform:none !important;letter-spacing:0.01em !important;box-shadow:inset 0 1px 0 rgba(255,255,255,0.9),0 4px 10px rgba(74,63,135,0.18) !important;transform:rotate(-4deg) !important;}}
body.theme-aero .wc-block-cart__sidebar,body.theme-aero .wc-block-checkout__sidebar,body.theme-aero .wp-block-woocommerce-cart-totals-block,body.theme-aero .wp-block-woocommerce-checkout-totals-block{{background:rgba(255,255,255,0.6) !important;border:1px solid rgba(255,255,255,0.8) !important;border-radius:var(--wp--custom--radius--xl,36px) !important;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:inset 0 1px 0 rgba(255,255,255,0.9),0 18px 40px rgba(74,63,135,0.18) !important;}}
body.theme-aero .wo-payment-icons__icon{{background:linear-gradient(180deg,var(--wp--preset--color--surface) 0%,var(--wp--preset--color--chrome) 60%,var(--wp--preset--color--surface) 100%) !important;border:1px solid rgba(255,255,255,0.8) !important;border-radius:var(--wp--custom--radius--lg,24px) !important;box-shadow:inset 0 1px 0 rgba(255,255,255,0.95),0 2px 6px rgba(74,63,135,0.18) !important;}}
body.theme-aero .wp-block-search__inside-wrapper,body.theme-aero input[type="text"],body.theme-aero input[type="email"],body.theme-aero input[type="url"],body.theme-aero textarea,body.theme-aero select{{border-radius:var(--wp--custom--radius--lg,24px) !important;background:rgba(255,255,255,0.7) !important;border:1px solid rgba(212,196,242,0.8) !important;}}
body.theme-aero .wp-block-navigation .wp-block-navigation-item__content{{padding:var(--wp--preset--spacing--xs) var(--wp--preset--spacing--md) !important;border-radius:var(--wp--custom--radius--pill,9999px) !important;transition:background 160ms ease,color 160ms ease !important;}}
body.theme-aero .wp-block-navigation .wp-block-navigation-item__content:hover{{background:rgba(255,255,255,0.55) !important;color:var(--wp--preset--color--primary-hover) !important;}}
body.theme-aero .wp-block-navigation .wp-block-navigation-item__content::after{{display:none !important;}}
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


def append_for(theme: str) -> str:
    """Walk every chunk in CHUNKS for one theme. Skips chunks whose
    open-sentinel is already present so re-runs are no-ops."""
    path = ROOT / theme / "theme.json"
    text = path.read_text(encoding="utf-8")
    notes: list[str] = []
    for sentinel_open, _close, css, anchor in CHUNKS:
        if sentinel_open in text:
            notes.append(f"skip {sentinel_open}")
            continue
        flat = _flatten(css)
        escaped = _json_escape(flat)
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
    args = parser.parse_args(argv[1:])

    targets = args.themes or THEMES
    appended_any = False
    for t in targets:
        if t not in THEMES:
            print(f"unknown theme: {t}", file=sys.stderr)
            return 2
        result = append_for(t)
        print(result)
        # If anything other than 'skip' notes appeared, we mutated the
        # theme.json -- worth running snap.
        if "+" in result or "FAIL" in result:
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
