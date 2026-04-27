<?php
/**
 * Title: FAQ accordion
 * Slug: apiary/faq-accordion
 * Categories: apiary
 * Block Types: core/post-content
 * Description: Five-item FAQ section using the core Accordion block. Replace the questions and answers.
 * Keywords: faq, questions, accordion, support
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl"},"blockGap":"var:preset|spacing|xl"}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group" style="padding-top:var(--wp--preset--spacing--2-xl);padding-bottom:var(--wp--preset--spacing--2-xl)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'Quietly jarred, often asked', 'apiary' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:accordion -->
	<div role="group" class="wp-block-accordion">
		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'When will the batch arrive?', 'apiary' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Each batch is packed at the bench within a working day. Most land on your doorstep inside the week.', 'apiary' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'What if a jar turns up cracked?', 'apiary' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Write and we\'ll send a replacement jar from the next batch. We only ask that you bin broken glass safely — no need to post it back.', 'apiary' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'Do you ship past the county line?', 'apiary' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'We do. Rates are worked out at checkout based on jar count and destination; honey travels well but we pack it like it won\'t.', 'apiary' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'Can I track the batch?', 'apiary' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'A tracking link lands in your inbox the moment the courier collects the jars from the kitchen at the back of the barn.', 'apiary' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'How do I reach the beekeeper?', 'apiary' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Write to hello@example.com — the beekeeper reads every note between rounds of the hives and writes back within the working day.', 'apiary' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->
	</div>
	<!-- /wp:accordion -->
</div>
<!-- /wp:group -->
