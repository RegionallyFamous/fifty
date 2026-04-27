<?php
/**
 * Title: Brand story, image and text
 * Slug: azulejo/brand-story
 * Categories: azulejo
 * Block Types: core/post-content
 * Description: Two-column section pairing a brand photo with a short story. Replace the image and text.
 * Keywords: about, brand, story, two-column, media-text
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:media-text {"align":"wide","mediaPosition":"left","mediaType":"image","verticalAlignment":"center"} -->
	<div class="wp-block-media-text alignwide is-stacked-on-mobile is-vertically-aligned-center">
		<figure class="wp-block-media-text__media"></figure>
		<div class="wp-block-media-text__content">
			<!-- wp:paragraph {"fontSize":"xs","style":{"typography":{"letterSpacing":"var:custom|letter-spacing|wider","textTransform":"uppercase"}},"textColor":"tertiary"} -->
			<p class="has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Os nossos traços', 'azulejo' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:heading {"level":2} -->
			<h2 class="wp-block-heading"><?php esc_html_e( 'Tiles painted by the hand, a pattern at a time.', 'azulejo' ); ?></h2>
			<!-- /wp:heading -->

			<!-- wp:paragraph {"textColor":"secondary","fontSize":"md"} -->
			<p class="has-secondary-color has-text-color has-md-font-size"><?php esc_html_e( 'Every piece in the atelier is drawn, cut, glazed and fired on a street off the Rua da Madalena in Lisbon, at the same marble tables the oficina has used since 1962. We keep the cobalt oxide crushed by hand, the stencils traced from the grandmother’s sketchbooks, and the kiln at a temperature that has not changed in three generations.', 'azulejo' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:buttons -->
			<div class="wp-block-buttons">
				<!-- wp:button {"className":"is-style-outline"} -->
				<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button"><?php esc_html_e( 'Read from the firing log', 'azulejo' ); ?></a></div>
				<!-- /wp:button -->
			</div>
			<!-- /wp:buttons -->
		</div>
	</div>
	<!-- /wp:media-text -->
</div>
<!-- /wp:group -->
