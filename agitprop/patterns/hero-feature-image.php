<?php
/**
 * Title: Front-page hero feature image
 * Slug: chonk/hero-feature-image
 * Categories: chonk, featured
 * Block Types: core/post-content
 * Description: The chonk-hero__photo image. A single-product still composed in
 *              chonk's brutalist visual language (heavy black borders + flat
 *              fills + pink accent strap) — used as the showcase image inside
 *              the front-page hero card so the hero reads as "here is the
 *              object, look at it" rather than as a placeholder square.
 * Keywords: hero, image, featured, front
 * Viewport Width: 1280
 *
 * The image lives at chonk/playground/images/product-wo-portable-hole.jpg
 * which ships with the theme via bin/seed-playground-content.py and is
 * resolved at render time via get_theme_file_uri() so the URL is correct
 * three ways: inside Playground (theme is fetched from the GitHub
 * monorepo); inside a local install (same theme path); inside a clone
 * of chonk (the new theme's own playground/images/ folder is seeded with
 * the same imagery — different artwork per theme is allowed; just keep
 * the filename or override this pattern in the clone).
 *
 * Avoid hardcoding raw.githubusercontent.com URLs here — that ties the
 * theme to GitHub being reachable at render time, which fails offline
 * and for any user who installs the theme outside the monorepo context.
 */
?>
<!-- wp:image {"sizeSlug":"large","className":"chonk-hero__photo-img"} -->
<figure class="wp-block-image size-large chonk-hero__photo-img"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-portable-hole.jpg' ) ); ?>" alt="<?php esc_attr_e( 'Portable Hole — a flat black disc on a white card with a thick black border, pink "OPEN END SOLD SEPARATELY" tag at the bottom. Chonk\'s hero featured product.', 'chonk' ); ?>"/></figure>
<!-- /wp:image -->
