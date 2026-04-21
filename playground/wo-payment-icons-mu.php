<?php
/**
 * Wonders & Oddities accepted-payments strip (mu-plugin).
 *
 * Why this exists:
 *   The WC Blocks checkout ships a `cart-accepted-payment-methods-block`
 *   that renders generic Visa/MC/Amex/Discover SVG sprites. That block
 *   is opt-in (we explicitly include it in our seeded cart tree) but
 *   only renders on the cart page totals column, not on the checkout
 *   below the Place Order button — which is where premium storefronts
 *   put the trust strip ("we accept: Visa, Mastercard, Amex, Apple Pay,
 *   Google Pay"). This mu-plugin appends a small icon strip to:
 *
 *     - the cart-totals block (inside the cart-totals column)
 *     - the checkout-actions block (immediately after Place Order)
 *
 *   Each brand renders as a self-contained inline SVG pill so it looks
 *   like a real trust mark instead of a cramped text label that wraps
 *   awkwardly ("APPLE PAY" used to break onto two lines and the row
 *   read as a placeholder). Inline SVG keeps the strip dependency-free
 *   (no asset URLs, no sprite, no font-loading races) and renders
 *   identically across every theme. The pills use a white surface +
 *   thin neutral border by design — that's the convention for trust
 *   strips even on dark themes (Apple, Stripe, every modern checkout
 *   shows brand-colored marks on light pills) so the strip reads as a
 *   payments row rather than melting into the page chrome.
 *
 * Implementation:
 *   The cart and checkout pages are both WC Blocks pages, so the only
 *   reliable post-render hook is `wp_footer` + DOM injection. We attach
 *   one handler that finds the proceed-to-checkout / place-order button
 *   container and appends a `.wo-payment-icons` div if one isn't already
 *   present. The check is idempotent (if WC Blocks re-renders the page
 *   on an AJAX cart update, the new container is missing the strip and
 *   we re-inject; if it isn't, we do nothing).
 *
 * Trademark posture:
 *   These are simplified wordmark/glyph approximations for demo
 *   purposes — close enough to be recognised at a glance, not pixel-
 *   perfect copies of the registered marks. A production storefront
 *   would license the official mark assets from each network.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

add_action(
	'wp_footer',
	function () {
		if ( is_admin() ) {
			return;
		}
		// Only print on cart / checkout / order-pay pages — keeps the
		// JS shim from running on every page load on the storefront.
		if ( ! ( function_exists( 'is_cart' ) && ( is_cart() || is_checkout() ) ) ) {
			return;
		}
		?>
<script>
(function(){
	// Each entry: { name, svg } where svg is a complete <svg> string sized
	// to a 40x26 viewBox so every pill in the row renders at identical
	// dimensions. Brand glyphs are simplified hand-drawn SVG paths +
	// system-font wordmarks — recognisable at strip size without
	// pulling in the real licensed mark assets. A production
	// storefront would license the official marks from each network.
	var BRANDS = [
		{ name: 'Visa', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Visa" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#1A1F71"/>'
			+ '<text x="20" y="18" text-anchor="middle" '
			+ 'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" '
			+ 'font-weight="900" font-style="italic" font-size="13" letter-spacing="0.5" fill="#fff">VISA</text>'
			+ '</svg>'
		},
		{ name: 'Mastercard', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Mastercard" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#fff" stroke="#E5E5E5"/>'
			+ '<circle cx="16" cy="13" r="7" fill="#EB001B"/>'
			+ '<circle cx="24" cy="13" r="7" fill="#F79E1B"/>'
			// Where the two circles overlap, paint the lens with the
			// network's signature orange so the mark reads correctly
			// without depending on mix-blend-mode.
			+ '<path d="M20 8 a7 7 0 0 1 0 10 a7 7 0 0 1 0-10 z" fill="#FF5F00"/>'
			+ '</svg>'
		},
		{ name: 'American Express', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="American Express" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#1F72CD"/>'
			+ '<text x="20" y="17" text-anchor="middle" '
			+ 'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" '
			+ 'font-weight="800" font-size="9" letter-spacing="0.7" fill="#fff">AMEX</text>'
			+ '</svg>'
		},
		{ name: 'Discover', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Discover" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#fff" stroke="#E5E5E5"/>'
			// Smaller wordmark (font-size 5.5) + smaller orange ball
			// pinned to the right edge so the two never overlap. The
			// real Discover mark embeds the orange "spark" inside the
			// "o" of the wordmark; at 40px wide that detail isn\'t
			// readable so we anchor the ball at the right instead and
			// let the silhouette do the recognition work.
			+ '<text x="3" y="16" '
			+ 'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" '
			+ 'font-weight="700" font-size="5.5" letter-spacing="0.1" fill="#111">DISCOVER</text>'
			+ '<circle cx="35" cy="13" r="3" fill="#F76B1C"/>'
			+ '</svg>'
		},
		{ name: 'Apple Pay', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Apple Pay" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#000"/>'
			// Apple silhouette using the well-known 814x1000 vector at
			// scale 0.014 → fits a ~11.4x14px area, translated into the
			// left half of the pill so the "Pay" wordmark sits at x=22.
			// Two subpaths: the body with the bite + the leaf on top.
			+ '<g transform="translate(7 5.5) scale(0.014)" fill="#fff">'
			+ '<path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76.5 0-103.7 40.8-165.9 40.8s-105.6-57-155.5-127C46.7 790.7 0 663 0 541.8c0-194.4 126.4-297.5 250.8-297.5 66.1 0 121.2 43.4 162.7 43.4 39.5 0 101.1-46 176.3-46 28.5 0 130.9 2.6 198.3 99.2zm-234-181.5c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z"/>'
			+ '</g>'
			+ '<text x="21" y="17" '
			+ 'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" '
			+ 'font-weight="600" font-size="10" letter-spacing="0.2" fill="#fff">Pay</text>'
			+ '</svg>'
		},
		{ name: 'Google Pay', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Google Pay" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#fff" stroke="#E5E5E5"/>'
			// Stylised "G" in Google blue + grey "Pay" wordmark next
			// to it. The four-color G is too detailed at 26px tall to
			// read; a single-color G keeps the silhouette clear while
			// the wordmark carries the rest of the recognition.
			+ '<text x="6" y="18" '
			+ 'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" '
			+ 'font-weight="700" font-size="13" fill="#4285F4">G</text>'
			+ '<text x="16" y="17" '
			+ 'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" '
			+ 'font-weight="600" font-size="10" letter-spacing="0.2" fill="#5F6368">Pay</text>'
			+ '</svg>'
		}
	];
	function build(){
		var div = document.createElement('div');
		div.className = 'wo-payment-icons';
		var label = document.createElement('span');
		label.className = 'wo-payment-icons__label';
		label.textContent = 'We accept';
		div.appendChild(label);
		var list = document.createElement('span');
		list.className = 'wo-payment-icons__list';
		BRANDS.forEach(function(brand){
			var pill = document.createElement('span');
			pill.className = 'wo-payment-icons__icon';
			pill.setAttribute('role', 'img');
			pill.setAttribute('aria-label', brand.name);
			pill.innerHTML = brand.svg;
			list.appendChild(pill);
		});
		div.appendChild(list);
		return div;
	}
	function inject(){
		// Checkout: place-order actions block.
		var actions = document.querySelector('.wp-block-woocommerce-checkout-actions-block');
		if (actions && !actions.querySelector(':scope > .wo-payment-icons')) {
			actions.appendChild(build());
		}
		// Cart: bottom of totals column.
		var totals = document.querySelector('.wp-block-woocommerce-cart-totals-block');
		if (totals && !totals.querySelector(':scope > .wo-payment-icons')) {
			totals.appendChild(build());
		}
	}
	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', inject);
	} else {
		inject();
	}
	// WC Blocks re-renders the cart/checkout on every store mutation;
	// observe the body so we re-inject if the strip gets wiped.
	var mo = new MutationObserver(function(){ inject(); });
	mo.observe(document.body, { childList: true, subtree: true });
})();
</script>
		<?php
	},
	99
);
