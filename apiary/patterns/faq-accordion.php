<?php
/**
 * Title: FAQ accordion
 * Slug: lysholm/faq-accordion
 * Categories: lysholm
 * Block Types: core/post-content
 * Description: Five-item FAQ section using the core Accordion block. Replace the questions and answers.
 * Keywords: faq, questions, accordion, support
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl"},"blockGap":"var:preset|spacing|xl"}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group" style="padding-top:var(--wp--preset--spacing--2-xl);padding-bottom:var(--wp--preset--spacing--2-xl)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'Quietly asked', 'lysholm' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:accordion -->
	<div role="group" class="wp-block-accordion">
		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'When does the parcel arrive?', 'lysholm' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Each parcel is wrapped at the studio within a day or two. Most arrive at your door inside the week.', 'lysholm' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'What if it doesn\'t suit the room?', 'lysholm' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Return any unused piece within 30 days, on us. We\'ll see it placed in a home that fits it better.', 'lysholm' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'Do you post past the country?', 'lysholm' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Yes — we post worldwide. Rates are quietly calculated at checkout based on parcel weight and destination.', 'lysholm' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'Can I follow the parcel home?', 'lysholm' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'A tracking link arrives in your inbox the moment the carrier collects the parcel from the studio.', 'lysholm' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'How do I reach the studio?', 'lysholm' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Write to hello@example.com — a maker reads every note and replies within a quiet working day.', 'lysholm' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->
	</div>
	<!-- /wp:accordion -->
</div>
<!-- /wp:group -->
