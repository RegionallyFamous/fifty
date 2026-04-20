<?php
/**
 * Title: Front feature — Bottled Morning
 * Slug: lysholm/front-feature
 * Categories: lysholm, featured
 * Description: Editorial 58/42 media-text feature block used on the front page.
 *              The product image is loaded from the theme's own
 *              playground/images/ folder so the block survives offline use and
 *              clones (see hero-split.php for the full reasoning).
 * Keywords: feature, media-text, editorial
 * Viewport Width: 1280
 */
?>
<!-- wp:media-text {"align":"wide","mediaPosition":"left","mediaWidth":58,"verticalAlignment":"center","mediaSizeSlug":"large","mediaUrl":"","style":{"spacing":{"blockGap":"var:preset|spacing|2-xl"}}} -->
<div class="wp-block-media-text alignwide is-stacked-on-mobile is-vertically-aligned-center" style="grid-template-columns:58% auto"><figure class="wp-block-media-text__media"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-bottled-morning.jpg' ) ); ?>" alt="<?php esc_attr_e( 'A bottle of morning light, photographed in oat-toned natural light against a chalk-white linen backdrop.', 'lysholm' ); ?>" class="size-full" /></figure>
	<div class="wp-block-media-text__content">
		<!-- wp:paragraph {"fontSize":"xs","textColor":"tertiary","style":{"typography":{"letterSpacing":"var(--wp--custom--letter-spacing--widest)","textTransform":"uppercase"}}} -->
		<p class="has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--widest);text-transform:uppercase"><?php esc_html_e( 'Object of the week', 'lysholm' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:heading {"level":2,"fontSize":"3-xl","style":{"spacing":{"margin":{"top":"var:preset|spacing|sm","bottom":"var:preset|spacing|md"}},"typography":{"fontWeight":"var(--wp--custom--font-weight--thin)"}}} -->
		<h2 class="wp-block-heading has-3-xl-font-size" style="margin-top:var(--wp--preset--spacing--sm);margin-bottom:var(--wp--preset--spacing--md);font-weight:var(--wp--custom--font-weight--thin)"><?php esc_html_e( 'Bottled Morning', 'lysholm' ); ?></h2>
		<!-- /wp:heading -->

		<!-- wp:paragraph {"fontSize":"base","textColor":"secondary","style":{"typography":{"lineHeight":"var(--wp--custom--line-height--relaxed)"}}} -->
		<p class="has-secondary-color has-text-color has-base-font-size" style="line-height:var(--wp--custom--line-height--relaxed)"><?php esc_html_e( 'Hand-stoppered glass, warm light caught at the rim. One per day, kept on the shelf for whenever the morning slips away from you.', 'lysholm' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:buttons {"style":{"spacing":{"margin":{"top":"var:preset|spacing|lg"}}}} -->
		<div class="wp-block-buttons" style="margin-top:var(--wp--preset--spacing--lg)">
			<!-- wp:button {"className":"is-style-outline"} -->
			<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button" href="/product/bottled-morning/"><?php esc_html_e( 'View the object', 'lysholm' ); ?></a></div>
			<!-- /wp:button -->
		</div>
		<!-- /wp:buttons -->
	</div>
</div>
<!-- /wp:media-text -->
