<?php
/**
 * Title: Account call-to-action
 * Slug: agitprop/account-cta
 * Categories: agitprop, call-to-action
 * Block Types: core/post-content
 * Description: Quiet sign-in / register prompt that uses the real woocommerce/customer-account block. Renders the account icon for logged-in shoppers and a sign-in link for everyone else — no fake fields, no third-party form provider needed.
 * Keywords: account, login, register, sign in
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"contrast","textColor":"base","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"},"blockGap":"var:preset|spacing|sm"}},"layout":{"type":"constrained","contentSize":"var(--wp--custom--layout--comfortable)"}} -->
<div class="wp-block-group alignfull has-base-color has-contrast-background-color has-text-color has-background" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center","level":2,"textColor":"base","style":{"spacing":{"margin":{"top":"0","bottom":"0"}}}} -->
	<h2 class="wp-block-heading has-text-align-center has-base-color has-text-color" style="margin-top:0;margin-bottom:0"><?php esc_html_e( 'Monitor your dispatches.', 'agitprop' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:paragraph {"align":"center","textColor":"base","style":{"spacing":{"margin":{"top":"0","bottom":"var:preset|spacing|md"}}}} -->
	<p class="has-text-align-center has-base-color has-text-color" style="margin-top:0;margin-bottom:var(--wp--preset--spacing--md)"><?php esc_html_e( 'Your print history, delivery addresses, and reserve list sit behind one login. Returning subscriber? Pick up where you left off.', 'agitprop' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:buttons {"layout":{"type":"flex","justifyContent":"center"},"style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
	<div class="wp-block-buttons">
		<!-- wp:button {"backgroundColor":"base","textColor":"contrast","style":{"border":{"radius":"0"}}} -->
		<div class="wp-block-button"><a class="wp-block-button__link has-contrast-color has-base-background-color has-text-color has-background wp-element-button" href="/my-account/" style="border-radius:0"><?php esc_html_e( 'Sign in', 'agitprop' ); ?></a></div>
		<!-- /wp:button -->

		<!-- wp:button {"textColor":"base","className":"is-style-outline","style":{"border":{"radius":"0"}}} -->
		<div class="wp-block-button is-style-outline"><a class="wp-block-button__link has-base-color has-text-color wp-element-button" href="/my-account/" style="border-radius:0"><?php esc_html_e( 'Register your operative file', 'agitprop' ); ?></a></div>
		<!-- /wp:button -->
	</div>
	<!-- /wp:buttons -->
</div>
<!-- /wp:group -->
