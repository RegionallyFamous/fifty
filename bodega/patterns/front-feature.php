<?php
/**
 * Title: Front feature — Bodega counter 4597a2
 * Slug: bodega/front-feature
 * Categories: bodega, featured
 * Description: Editorial 58/42 media-text feature block used on the front page.
 *              The product image is loaded from the theme's own
 *              playground/images/ folder so the block survives offline use and
 *              clones (see hero-split.php for the full reasoning).
 * Keywords: feature, media-text, editorial
 * Viewport Width: 1280
 */
?>
<!-- wp:media-text {"align":"wide","mediaPosition":"left","mediaWidth":58,"verticalAlignment":"center","mediaType":"image","mediaSizeSlug":"large","mediaLink":"<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-bottled-morning.jpg' ) ); ?>","mediaUrl":"<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-bottled-morning.jpg' ) ); ?>","mediaAlt":"<?php echo esc_attr__( 'Bodega parcel-room copy 4c2a6e', 'bodega' ); ?>","style":{"spacing":{"blockGap":"var:preset|spacing|2-xl"}}} -->
<div class="wp-block-media-text alignwide is-stacked-on-mobile is-vertically-aligned-center" style="grid-template-columns:58% auto"><figure class="wp-block-media-text__media"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-bottled-morning.jpg' ) ); ?>" alt="<?php echo esc_attr__( 'Bodega parcel-room copy 4c2a6e', 'bodega' ); ?>"/></figure>
	<div class="wp-block-media-text__content">
		<!-- wp:paragraph {"fontSize":"xs","textColor":"tertiary","style":{"typography":{"letterSpacing":"var(--wp--custom--letter-spacing--widest)","textTransform":"uppercase"}}} -->
		<p class="has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--widest);text-transform:uppercase"><?php esc_html_e( 'Bodega counter 4ec741', 'bodega' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:heading {"level":2,"fontSize":"3-xl","style":{"spacing":{"margin":{"top":"var:preset|spacing|sm","bottom":"var:preset|spacing|md"}},"typography":{"fontWeight":"var(--wp--custom--font-weight--thin)"}}} -->
		<h2 class="wp-block-heading has-3-xl-font-size" style="margin-top:var(--wp--preset--spacing--sm);margin-bottom:var(--wp--preset--spacing--md);font-weight:var(--wp--custom--font-weight--thin)"><?php esc_html_e( 'Bodega counter 4597a2', 'bodega' ); ?></h2>
		<!-- /wp:heading -->

		<!-- wp:paragraph {"fontSize":"base","textColor":"secondary","style":{"typography":{"lineHeight":"var(--wp--custom--line-height--relaxed)"}}} -->
		<p class="has-secondary-color has-text-color has-base-font-size" style="line-height:var(--wp--custom--line-height--relaxed)"><?php esc_html_e( 'Bodega parcel-room copy 719205', 'bodega' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:buttons {"style":{"spacing":{"margin":{"top":"var:preset|spacing|lg"}}}} -->
		<div class="wp-block-buttons" style="margin-top:var(--wp--preset--spacing--lg)">
			<!-- wp:button {"className":"is-style-outline"} -->
			<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button" href="/product/bottled-morning/"><?php esc_html_e( 'Bodega counter d48128', 'bodega' ); ?></a></div>
			<!-- /wp:button -->
		</div>
		<!-- /wp:buttons -->
	</div>
</div>
<!-- /wp:media-text -->
