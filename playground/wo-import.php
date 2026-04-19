<?php
/**
 * Wonders & Oddities sample-data importer for WordPress Playground.
 *
 * Run via `wp eval-file /wordpress/wo-import.php` after the file has been
 * fetched into the Playground filesystem by a `writeFile` blueprint step.
 *
 * Why this script exists:
 *   The previous version of this importer leaned on
 *   WC_Product_CSV_Importer + WC_Product_CSV_Importer_Controller, which is
 *   not part of WooCommerce's stable public surface. Across WC versions the
 *   helper methods have flipped between public/protected, static/instance,
 *   and the importer's read_file() rejects any path that does not look like
 *   a CSV upload. Each WC release broke the blueprint in a new way.
 *
 *   This rewrite uses only WC's stable public CRUD API:
 *     - WC_Product_Simple / WC_Product_Variable / WC_Product_Grouped /
 *       WC_Product_External
 *     - the standard set_*() setters
 *     - wc_get_product_id_by_sku()
 *     - wp_insert_term() / get_term_by()
 *
 *   These have been stable for years and do not depend on any internal
 *   importer plumbing.
 *
 * The CSV is the canonical Wonders & Oddities products file. We parse it
 * directly with PHP's str_getcsv() and create one product per row.
 *
 * The script is idempotent: products are looked up by SKU and skipped if
 * they already exist, so re-running the blueprint will not create
 * duplicates.
 *
 * Product images are sideloaded from the URLs in the CSV's "Images"
 * column (comma-separated; first becomes the featured image, the rest
 * become the gallery). Each fetch is wrapped in its own try/catch so a
 * single 404 or upstream timeout drops just that image and lets the
 * product save with whatever else loaded.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( ! class_exists( 'WooCommerce' ) ) {
	WP_CLI::error( 'WooCommerce is not active. Aborting W&O import.' );
}

// WO_CONTENT_BASE_URL is prepended to this script by bin/sync-playground.py
// when the script is inlined into each theme's blueprint.json. It points at
// the per-theme playground/ directory on raw.githubusercontent.com, e.g.
//     https://raw.githubusercontent.com/RegionallyFamous/fifty/main/obel/playground/
// so this importer pulls content/products.csv from the SAME theme that
// served the blueprint. Each theme owns its own catalogue and product
// imagery -- divergent copy and styling are first-class.
//
// The fallback to the upstream wonders-oddities repo is intentional: if a
// developer runs `wp eval-file wo-import.php` directly without the sync
// script having defined the constant (e.g. while debugging), we still get
// a working catalogue from the original source.
$wo_content_base = defined( 'WO_CONTENT_BASE_URL' )
	? WO_CONTENT_BASE_URL
	: 'https://raw.githubusercontent.com/RegionallyFamous/wonders-oddities/main/';
$wo_csv_url = rtrim( $wo_content_base, '/' ) . '/content/products.csv';
// Legacy fallback: the upstream wonders-oddities repo doesn't have a
// content/ subdirectory -- the CSV sits at the repo root. Detect that
// case so the script stays runnable against the original source.
if ( false !== strpos( $wo_content_base, 'wonders-oddities' ) ) {
	$wo_csv_url = rtrim( $wo_content_base, '/' ) . '/wonders-oddities-products.csv';
}

/**
 * Walk a "Parent > Child > Grandchild" category path, creating any missing
 * terms. Returns the leaf term_id, or 0 if the path could not be resolved.
 *
 * Caches resolved paths so repeated lookups across rows are cheap and so
 * that the same term is not inserted twice when WP's term cache is cold.
 */
function wo_resolve_category_path( string $path ): int {
	static $cache = array();

	$path = trim( $path );
	if ( '' === $path ) {
		return 0;
	}
	if ( isset( $cache[ $path ] ) ) {
		return $cache[ $path ];
	}

	$segments = array_filter( array_map( 'trim', explode( '>', $path ) ), 'strlen' );
	$parent   = 0;
	$term_id  = 0;

	foreach ( $segments as $name ) {
		$existing = get_terms(
			array(
				'taxonomy'   => 'product_cat',
				'name'       => $name,
				'parent'     => $parent,
				'hide_empty' => false,
				'number'     => 1,
			)
		);

		if ( ! is_wp_error( $existing ) && ! empty( $existing ) ) {
			$term_id = (int) $existing[0]->term_id;
		} else {
			$inserted = wp_insert_term( $name, 'product_cat', array( 'parent' => $parent ) );
			if ( is_wp_error( $inserted ) ) {
				$term_id = 0;
				break;
			}
			$term_id = (int) $inserted['term_id'];
		}

		$parent = $term_id;
	}

	return $cache[ $path ] = $term_id;
}

/**
 * Resolve (or create) a flat product_tag term by name. Returns 0 on failure
 * so the caller can simply drop unresolvable tags rather than aborting the
 * whole row.
 */
function wo_resolve_tag( string $name ): int {
	static $cache = array();

	$name = trim( $name );
	if ( '' === $name ) {
		return 0;
	}
	if ( isset( $cache[ $name ] ) ) {
		return $cache[ $name ];
	}

	$existing = get_term_by( 'name', $name, 'product_tag' );
	if ( $existing ) {
		return $cache[ $name ] = (int) $existing->term_id;
	}

	$inserted = wp_insert_term( $name, 'product_tag' );
	if ( is_wp_error( $inserted ) ) {
		return $cache[ $name ] = 0;
	}
	return $cache[ $name ] = (int) $inserted['term_id'];
}

/**
 * Best-effort cast of WC's truthy-ish CSV cell values ("1", "yes", "no",
 * "true", "") to a real bool. Anything ambiguous becomes false so we never
 * accidentally publish or feature a product the source CSV did not intend.
 */
function wo_truthy( $value ): bool {
	$value = strtolower( trim( (string) $value ) );
	return in_array( $value, array( '1', 'yes', 'true' ), true );
}

/**
 * Sideload a single image URL into the media library and return the new
 * attachment ID, or 0 on failure.
 *
 * Caches by URL so the same image referenced by multiple products is only
 * downloaded once per import run. Looks for an existing attachment with a
 * matching _wo_source_url meta first, so re-running the blueprint
 * (idempotent by SKU at the product level) also avoids re-downloading
 * images that already landed in a previous run.
 *
 * media_sideload_image() lives in wp-admin/includes/media.php and pulls in
 * file.php and image.php transitively; we require all three explicitly so
 * the function exists in the wp-cli context where wp-admin isn't loaded by
 * default.
 */
function wo_sideload_image( string $url, int $parent_post_id ): int {
	static $cache = array();

	$url = trim( $url );
	if ( '' === $url ) {
		return 0;
	}
	if ( isset( $cache[ $url ] ) ) {
		return $cache[ $url ];
	}

	$existing = get_posts(
		array(
			'post_type'      => 'attachment',
			'meta_key'       => '_wo_source_url',
			'meta_value'     => $url,
			'posts_per_page' => 1,
			'fields'         => 'ids',
			'no_found_rows'  => true,
		)
	);
	if ( ! empty( $existing ) ) {
		return $cache[ $url ] = (int) $existing[0];
	}

	require_once ABSPATH . 'wp-admin/includes/file.php';
	require_once ABSPATH . 'wp-admin/includes/image.php';
	require_once ABSPATH . 'wp-admin/includes/media.php';

	$id = media_sideload_image( $url, $parent_post_id, null, 'id' );
	if ( is_wp_error( $id ) || ! $id ) {
		return $cache[ $url ] = 0;
	}

	update_post_meta( (int) $id, '_wo_source_url', $url );
	return $cache[ $url ] = (int) $id;
}

$response = wp_remote_get(
	$wo_csv_url,
	array( 'timeout' => 60 )
);

if ( is_wp_error( $response ) ) {
	WP_CLI::error( 'Failed to fetch W&O CSV: ' . $response->get_error_message() );
}

$body = wp_remote_retrieve_body( $response );
if ( '' === $body ) {
	WP_CLI::error( 'W&O CSV body was empty (HTTP ' . wp_remote_retrieve_response_code( $response ) . ').' );
}

// Normalize line endings then split into rows. We do this manually rather
// than writing the body to a temp file because WC's CSV reader insists the
// file be at a path with a .csv extension and a matching wp_check_filetype
// MIME — both of which are easy to get wrong inside Playground's WASM PHP.
$lines = preg_split( '/\r\n|\r|\n/', trim( $body ) );
if ( count( $lines ) < 2 ) {
	WP_CLI::error( 'W&O CSV looked malformed: fewer than 2 lines after trim.' );
}

$headers = str_getcsv( array_shift( $lines ) );
$num     = count( $headers );

$created = 0;
$skipped = 0;
$failed  = 0;

foreach ( $lines as $line ) {
	if ( '' === trim( $line ) ) {
		continue;
	}

	$cells = str_getcsv( $line );
	// Pad/truncate to header width so array_combine() never fatals on
	// rows that have an unexpected column count.
	if ( count( $cells ) < $num ) {
		$cells = array_pad( $cells, $num, '' );
	} elseif ( count( $cells ) > $num ) {
		$cells = array_slice( $cells, 0, $num );
	}
	$row = array_combine( $headers, $cells );

	$sku = trim( (string) ( $row['SKU'] ?? '' ) );
	if ( '' !== $sku && wc_get_product_id_by_sku( $sku ) ) {
		++$skipped;
		continue;
	}

	$type = strtolower( trim( (string) ( $row['Type'] ?? 'simple' ) ) );
	switch ( $type ) {
		case 'variable':
			$product = new WC_Product_Variable();
			break;
		case 'grouped':
			$product = new WC_Product_Grouped();
			break;
		case 'external':
			$product = new WC_Product_External();
			break;
		default:
			$product = new WC_Product_Simple();
			break;
	}

	// External and grouped products do not support stock management or
	// physical dimensions in WC; calling the setters throws
	// WC_Data_Exception. Gate by type instead of guarding every setter.
	$supports_stock = $product->is_type( 'simple' ) || $product->is_type( 'variable' );
	$supports_dims  = ! $product->is_type( 'external' ) && ! $product->is_type( 'grouped' );

	// Set everything inside a single try/catch so an unexpected
	// rejection from any one setter (new validation rule, schema
	// change) only loses this row instead of the whole import.
	try {
		$product->set_name( (string) ( $row['Name'] ?? '' ) );
		$product->set_status( wo_truthy( $row['Published'] ?? '1' ) ? 'publish' : 'draft' );
		if ( '' !== $sku ) {
			$product->set_sku( $sku );
		}
		$product->set_description( (string) ( $row['Description'] ?? '' ) );
		$product->set_short_description( (string) ( $row['Short description'] ?? '' ) );
		$product->set_featured( wo_truthy( $row['Is featured?'] ?? '0' ) );

		$visibility = trim( (string) ( $row['Visibility in catalog'] ?? 'visible' ) );
		if ( in_array( $visibility, array( 'visible', 'catalog', 'search', 'hidden' ), true ) ) {
			$product->set_catalog_visibility( $visibility );
		}

		// Grouped products derive their price from children; setting one
		// directly is rejected. Skip pricing on grouped, allow it on
		// simple/variable/external.
		if ( ! $product->is_type( 'grouped' ) ) {
			$reg = trim( (string) ( $row['Regular price'] ?? '' ) );
			if ( '' !== $reg ) {
				$product->set_regular_price( $reg );
			}
			$sale = trim( (string) ( $row['Sale price'] ?? '' ) );
			if ( '' !== $sale ) {
				$product->set_sale_price( $sale );
			}
		}

		$tax_status = trim( (string) ( $row['Tax status'] ?? '' ) );
		if ( in_array( $tax_status, array( 'taxable', 'shipping', 'none' ), true ) ) {
			$product->set_tax_status( $tax_status );
		}

		if ( $supports_stock ) {
			if ( wo_truthy( $row['In stock?'] ?? '1' ) ) {
				$product->set_stock_status( 'instock' );
				$stock = trim( (string) ( $row['Stock'] ?? '' ) );
				if ( '' !== $stock && is_numeric( $stock ) ) {
					$product->set_manage_stock( true );
					$product->set_stock_quantity( (int) $stock );
				}
			} else {
				$product->set_stock_status( 'outofstock' );
			}
		}

		if ( $supports_dims ) {
			foreach ( array( 'Weight (kg)' => 'set_weight', 'Length (cm)' => 'set_length', 'Width (cm)' => 'set_width', 'Height (cm)' => 'set_height' ) as $key => $setter ) {
				$value = trim( (string) ( $row[ $key ] ?? '' ) );
				if ( '' !== $value && is_numeric( $value ) ) {
					$product->{$setter}( $value );
				}
			}
		}

		// External-only fields. Both have safe defaults if missing.
		if ( $product->is_type( 'external' ) ) {
			$ext_url = trim( (string) ( $row['External URL'] ?? '' ) );
			if ( '' !== $ext_url ) {
				$product->set_product_url( $ext_url );
			}
			$button = trim( (string) ( $row['Button text'] ?? '' ) );
			if ( '' !== $button ) {
				$product->set_button_text( $button );
			}
		}
		$cat_ids = array();
		$cats    = trim( (string) ( $row['Categories'] ?? '' ) );
		if ( '' !== $cats ) {
			foreach ( explode( ',', $cats ) as $cat_path ) {
				$tid = wo_resolve_category_path( $cat_path );
				if ( $tid ) {
					$cat_ids[] = $tid;
				}
			}
		}
		if ( ! empty( $cat_ids ) ) {
			$product->set_category_ids( array_values( array_unique( $cat_ids ) ) );
		}

		$tag_ids = array();
		$tags    = trim( (string) ( $row['Tags'] ?? '' ) );
		if ( '' !== $tags ) {
			foreach ( explode( ',', $tags ) as $tag_name ) {
				$tid = wo_resolve_tag( $tag_name );
				if ( $tid ) {
					$tag_ids[] = $tid;
				}
			}
		}
		if ( ! empty( $tag_ids ) ) {
			$product->set_tag_ids( array_values( array_unique( $tag_ids ) ) );
		}

		$product_id = $product->save();

		// Images are attached after the initial save so each attachment
		// can record its parent post ID. We re-fetch the product object
		// before the second save so the image-id setters operate on a
		// fresh CRUD instance with no stale cached data.
		$image_urls = array_filter(
			array_map( 'trim', explode( ',', (string) ( $row['Images'] ?? '' ) ) ),
			'strlen'
		);
		if ( ! empty( $image_urls ) && $product_id ) {
			$attachment_ids = array();
			foreach ( $image_urls as $img_url ) {
				$att_id = wo_sideload_image( $img_url, $product_id );
				if ( $att_id ) {
					$attachment_ids[] = $att_id;
				}
			}
			if ( ! empty( $attachment_ids ) ) {
				$product = wc_get_product( $product_id );
				$product->set_image_id( (int) array_shift( $attachment_ids ) );
				if ( ! empty( $attachment_ids ) ) {
					$product->set_gallery_image_ids( array_values( array_unique( $attachment_ids ) ) );
				}
				$product->save();
			}
		}

		++$created;
	} catch ( Exception $e ) {
		++$failed;
		WP_CLI::warning( sprintf( 'Skipping "%s" (SKU %s, type %s): %s', $row['Name'] ?? '?', $sku, $type, $e->getMessage() ) );
	}
}

WP_CLI::success(
	sprintf(
		'W&O import done. Created=%d Skipped=%d Failed=%d',
		$created,
		$skipped,
		$failed
	)
);
