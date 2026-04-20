<?php
/**
 * Title: Hero — split (text + image)
 * Slug: lysholm/hero-split
 * Categories: lysholm, featured
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
 *   3. Inside a clone of lysholm — the new theme's own playground/images/
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
			<h1 class="wp-block-heading has-5-xl-font-size"><?php esc_html_e( 'Designed for commerce.', 'lysholm' ); ?></h1>
			<!-- /wp:heading -->

			<!-- wp:paragraph {"fontSize":"md","textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color has-md-font-size"><?php esc_html_e( 'A block-only WooCommerce theme. Composed entirely of core blocks, styled entirely from one design file.', 'lysholm' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:buttons {"style":{"spacing":{"margin":{"top":"var:preset|spacing|md"}}}} -->
			<div class="wp-block-buttons" style="margin-top:var(--wp--preset--spacing--md)">
				<!-- wp:button -->
				<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="/shop"><?php esc_html_e( 'Shop the collection', 'lysholm' ); ?></a></div>
				<!-- /wp:button -->

				<!-- wp:button {"className":"is-style-outline"} -->
				<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button" href="/journal"><?php esc_html_e( 'Read the journal', 'lysholm' ); ?></a></div>
				<!-- /wp:button -->
			</div>
			<!-- /wp:buttons -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column {"verticalAlignment":"center"} -->
		<div class="wp-block-column is-vertically-aligned-center">
			<!-- wp:image {"sizeSlug":"large","style":{"dimensions":{"aspectRatio":"var(--wp--custom--aspect-ratio--widescreen)"}}} -->
			<figure class="wp-block-image size-large" style="aspect-ratio:var(--wp--custom--aspect-ratio--widescreen)"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-bottled-morning.jpg' ) ); ?>" alt="<?php esc_attr_e( 'Bottled Morning — a cork-stoppered glass bottle of warm light, tagged in coral linen on a soft natural backdrop. The flagship product of the Wonders &amp; Oddities demo catalogue.', 'lysholm' ); ?>" /></figure>
			<!-- /wp:image -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->
