<?php
/**
 * Title: Hero — ornate apothecary card
 * Slug: atomic/hero-split
 * Categories: atomic, featured
 * Block Types: core/post-content
 * Description: Victorian-apothecary hero: a cream card framed by hairline ornamental
 *              borders, a centered Roman-numeral eyebrow, a display-serif headline flanked
 *              by fleuron glyphs, an italic deck and a single "enter the shop" call to
 *              action. Replaces the stock split hero: Foundry's front page is a shop card,
 *              not a promo grid.
 * Keywords: hero, apothecary, ornate, boxed, shop card, victorian
 * Viewport Width: 1280
 *
 * The hero renders entirely in core blocks — fleurons are literal Unicode (❦) so the
 * "engraved shop card" feel survives even when no image assets are present.
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|md","right":"var:preset|spacing|md"}}},"backgroundColor":"base","layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull has-base-background-color has-background" style="padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--md);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--md)">
	<!-- wp:group {"align":"wide","className":"foundry-hero-card","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|2-xl","right":"var:preset|spacing|2-xl"},"blockGap":"var:preset|spacing|md"},"border":{"color":"var:preset|color|border","style":"double","width":"4px","radius":"2px"}},"backgroundColor":"surface","layout":{"type":"constrained"}} -->
	<div class="wp-block-group alignwide foundry-hero-card has-border-color has-surface-background-color has-background" style="border-color:var(--wp--preset--color--border);border-style:double;border-width:4px;border-radius:2px;padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--2-xl);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--2-xl)">
		<!-- wp:paragraph {"align":"center","fontSize":"xs","textColor":"tertiary","style":{"typography":{"letterSpacing":"var(--wp--custom--letter-spacing--engraved)","textTransform":"uppercase","fontWeight":"500"}}} -->
		<p class="has-text-align-center has-tertiary-color has-text-color has-xs-font-size" style="font-weight:500;letter-spacing:var(--wp--custom--letter-spacing--engraved);text-transform:uppercase"><?php esc_html_e( 'Est. 1957 &mdash; Pad no. 7, Tomorrow Boulevard', 'atomic' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:paragraph {"align":"center","textColor":"accent","fontSize":"xl","style":{"typography":{"lineHeight":"1"},"spacing":{"margin":{"top":"var:preset|spacing|sm","bottom":"0"}}},"fontFamily":"display"} -->
		<p class="has-text-align-center has-accent-color has-text-color has-xl-font-size has-display-font-family" style="margin-top:var(--wp--preset--spacing--sm);margin-bottom:0;line-height:1">&#9737; &nbsp;&middot;&nbsp; &#9737;</p>
		<!-- /wp:paragraph -->

		<!-- wp:heading {"textAlign":"center","level":1,"fontSize":"4-xl","style":{"typography":{"lineHeight":"1.05","fontStyle":"normal","fontWeight":"600","letterSpacing":"var(--wp--custom--letter-spacing--tight)"},"spacing":{"margin":{"top":"var:preset|spacing|sm","bottom":"var:preset|spacing|sm"}}},"fontFamily":"display"} -->
		<h1 class="wp-block-heading has-text-align-center has-display-font-family has-4-xl-font-size" style="margin-top:var(--wp--preset--spacing--sm);margin-bottom:var(--wp--preset--spacing--sm);font-style:normal;font-weight:600;letter-spacing:var(--wp--custom--letter-spacing--tight);line-height:1.05"><?php esc_html_e( 'Space-age wonders, hand-finished.', 'atomic' ); ?></h1>
		<!-- /wp:heading -->

		<!-- wp:paragraph {"align":"center","fontSize":"md","textColor":"secondary","style":{"typography":{"fontStyle":"italic","fontWeight":"400","lineHeight":"var(--wp--custom--line-height--relaxed)"},"spacing":{"margin":{"top":"0","bottom":"var:preset|spacing|md"}}},"fontFamily":"serif"} -->
		<p class="has-text-align-center has-secondary-color has-text-color has-md-font-size has-serif-font-family" style="margin-top:0;margin-bottom:var(--wp--preset--spacing--md);font-style:italic;font-weight:400;line-height:var(--wp--custom--line-height--relaxed)"><?php esc_html_e( 'Boomerang trays, starburst ties, rocket-shaped staplers &mdash; all designed for the tomorrow we promised ourselves in 1957, all hand-assembled on the pad and launched the same Tuesday afternoon.', 'atomic' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:separator {"backgroundColor":"border","style":{"spacing":{"margin":{"top":"var:preset|spacing|md","bottom":"var:preset|spacing|md"}}},"className":"is-style-dots"} -->
		<hr class="wp-block-separator has-alpha-channel-opacity has-text-color has-border-color has-border-background-color has-background is-style-dots" style="margin-top:var(--wp--preset--spacing--md);margin-bottom:var(--wp--preset--spacing--md)"/>
		<!-- /wp:separator -->

		<!-- wp:buttons {"layout":{"type":"flex","justifyContent":"center"},"style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
		<div class="wp-block-buttons">
			<!-- wp:button {"className":"is-style-fill"} -->
			<div class="wp-block-button is-style-fill"><a class="wp-block-button__link wp-element-button" href="/shop"><?php esc_html_e( 'Tour the showroom &rsaquo;', 'atomic' ); ?></a></div>
			<!-- /wp:button -->

			<!-- wp:button {"className":"is-style-outline"} -->
			<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button" href="/journal"><?php esc_html_e( 'Open the mission log', 'atomic' ); ?></a></div>
			<!-- /wp:button -->
		</div>
		<!-- /wp:buttons -->
	</div>
	<!-- /wp:group -->
</div>
<!-- /wp:group -->
