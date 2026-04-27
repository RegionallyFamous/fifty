<?php
/**
 * Title: Front feature — Forbidden Honey
 * Slug: apiary/front-feature
 * Categories: apiary, featured
 * Description: Editorial 58/42 media-text feature block used on the front page.
 *              The product image is loaded from the theme's own
 *              playground/images/ folder so the block survives offline use and
 *              clones (see hero-split.php for the full reasoning).
 * Keywords: feature, media-text, editorial
 * Viewport Width: 1280
 */
?>
<!-- wp:media-text {"align":"wide","mediaPosition":"left","mediaWidth":58,"verticalAlignment":"center","mediaType":"image","mediaSizeSlug":"large","mediaLink":"<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-forbidden-honey.jpg' ) ); ?>","mediaUrl":"<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-forbidden-honey.jpg' ) ); ?>","mediaAlt":"<?php echo esc_attr__( 'A jar of dark amber honey on a cream-linen cloth, backlit butter-yellow, with a hand-drawn bee penciled on the paper label.', 'apiary' ); ?>","style":{"spacing":{"blockGap":"var:preset|spacing|2-xl"}}} -->
<div class="wp-block-media-text alignwide is-stacked-on-mobile is-vertically-aligned-center" style="grid-template-columns:58% auto"><figure class="wp-block-media-text__media"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-forbidden-honey.jpg' ) ); ?>" alt="<?php echo esc_attr__( 'A jar of dark amber honey on a cream-linen cloth, backlit butter-yellow, with a hand-drawn bee penciled on the paper label.', 'apiary' ); ?>"/></figure>
	<div class="wp-block-media-text__content">
		<!-- wp:paragraph {"fontSize":"xs","textColor":"tertiary","style":{"typography":{"letterSpacing":"var(--wp--custom--letter-spacing--widest)","textTransform":"uppercase"}}} -->
		<p class="has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--widest);text-transform:uppercase"><?php esc_html_e( 'Jar of the month', 'apiary' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:heading {"level":2,"fontSize":"3-xl","style":{"spacing":{"margin":{"top":"var:preset|spacing|sm","bottom":"var:preset|spacing|md"}},"typography":{"fontWeight":"var(--wp--custom--font-weight--thin)"}}} -->
		<h2 class="wp-block-heading has-3-xl-font-size" style="margin-top:var(--wp--preset--spacing--sm);margin-bottom:var(--wp--preset--spacing--md);font-weight:var(--wp--custom--font-weight--thin)"><?php esc_html_e( 'Forbidden Honey', 'apiary' ); ?></h2>
		<!-- /wp:heading -->

		<!-- wp:paragraph {"fontSize":"base","textColor":"secondary","style":{"typography":{"lineHeight":"var(--wp--custom--line-height--relaxed)"}}} -->
		<p class="has-secondary-color has-text-color has-base-font-size" style="line-height:var(--wp--custom--line-height--relaxed)"><?php esc_html_e( 'A 340g jar of deep amber, drawn from hives keeping their own counsel at the edge of a back pasture. Batch 03, sealed the morning the comb came off. Pairs well with sourdough and a well-rehearsed legal defence.', 'apiary' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:buttons {"style":{"spacing":{"margin":{"top":"var:preset|spacing|lg"}}}} -->
		<div class="wp-block-buttons" style="margin-top:var(--wp--preset--spacing--lg)">
			<!-- wp:button {"className":"is-style-outline"} -->
			<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button" href="/product/forbidden-honey/"><?php esc_html_e( 'Open the jar', 'apiary' ); ?></a></div>
			<!-- /wp:button -->
		</div>
		<!-- /wp:buttons -->
	</div>
</div>
<!-- /wp:media-text -->
