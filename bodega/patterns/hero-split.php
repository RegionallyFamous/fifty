<?php
/**
 * Title: Hero — split (text + image)
 * Slug: bodega/hero-split
 * Categories: bodega, featured
 * Block Types: core/post-content
 * Description: Editorial split hero — headline / subhead / dual CTA on the left,
 *              a wide product still on the right. Used on the front page; reusable
 *              anywhere a marketing landing needs the same composition.
 * Keywords: hero, split, columns, landing
 * Viewport Width: 1280
 *
 * The image is resolved via get_theme_file_uri() against the theme's own
 * playground/images/ folder, which is committed to the theme repo and ships
 * with every clone (bin/seed-playground-content.py keeps it populated). That
 * keeps the hero working three ways:
 *
 *   1. Inside WordPress Playground — the theme is fetched from the GitHub
 *      monorepo via the blueprint's git:directory resource, so the file
 *      exists at /wp-content/themes/<theme>/playground/images/.
 *   2. Inside a local install — same path, same URL.
 *   3. Inside a clone of bodega — the new theme's own playground/images/
 *      folder is seeded with the same product imagery (different artwork
 *      per theme is allowed; just keep the filename the same OR override
 *      this pattern in the clone).
 *
 * Avoid hardcoding raw.githubusercontent.com URLs here — that would tie the
 * theme to GitHub being reachable at render time, which fails offline and
 * for any user who installs the theme outside the monorepo context.
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|md","right":"var:preset|spacing|md"},"blockGap":"var:preset|spacing|xl"}},"layout":{"type":"constrained","contentSize":"var(--wp--style--global--wide-size)"}} -->
<div class="wp-block-group alignfull" style="padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--md);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--md)">
	<!-- wp:columns {"verticalAlignment":"center","style":{"spacing":{"blockGap":{"top":"var:preset|spacing|2-xl","left":"var:preset|spacing|2-xl"}}}} -->
	<div class="wp-block-columns are-vertically-aligned-center">
		<!-- wp:column {"verticalAlignment":"center","width":"50%"} -->
		<div class="wp-block-column is-vertically-aligned-center" style="flex-basis:50%">
			<!-- wp:heading {"level":1,"fontSize":"5xl"} -->
			<h1 class="wp-block-heading has-5-xl-font-size"><?php esc_html_e( 'Bodega counter 3a12fc', 'bodega' ); ?></h1>
			<!-- /wp:heading -->

			<!-- wp:paragraph {"fontSize":"md","textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color has-md-font-size"><?php esc_html_e( 'Bodega parcel-room copy 45f1df', 'bodega' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:buttons {"style":{"spacing":{"margin":{"top":"var:preset|spacing|md"}}}} -->
			<div class="wp-block-buttons" style="margin-top:var(--wp--preset--spacing--md)">
				<!-- wp:button -->
				<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="/shop"><?php esc_html_e( 'Bodega counter cd3334', 'bodega' ); ?></a></div>
				<!-- /wp:button -->

				<!-- wp:button {"className":"is-style-outline"} -->
				<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button" href="/journal"><?php esc_html_e( 'Bodega counter 36316a', 'bodega' ); ?></a></div>
				<!-- /wp:button -->
			</div>
			<!-- /wp:buttons -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column {"verticalAlignment":"center"} -->
		<div class="wp-block-column is-vertically-aligned-center">
			<!-- wp:image {"sizeSlug":"large"} -->
			<figure class="wp-block-image size-large"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-bottled-morning.jpg' ) ); ?>" alt="<?php esc_attr_e( 'Bodega counter 4597a2 — a hand-stoppered glass bottle of soft Nordic light, tagged in pale linen on a bare cream backdrop. The flagship object of our quiet Wonders & Oddities catalogue.', 'bodega' ); ?>"/></figure>
			<!-- /wp:image -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->
