<?php
/**
 * Prepare the Urumi Supply storefront.
 *
 * Two things happen here:
 *
 * 1. The product illustrations are registered as media attachments. The SVGs
 *    ship inside the theme and WordPress does not allow SVG uploads by
 *    default, so instead of relaxing the upload rules the files are copied
 *    into the uploads directory and inserted as attachments whose mime type
 *    is `image/svg+xml`.
 * 2. The Cart and Checkout pages are switched from the WooCommerce blocks to
 *    the classic shortcodes so they use the theme templates.
 *
 * Run through WP-CLI (the theme must be active):
 *
 *   wp eval "$(sed '1d' scripts/woo_storefront.php)"
 *
 * It prints a single `URUMI_MANIFEST:{json}` line mapping SKU -> attachment id
 * and also writes the manifest to uploads/urumi-supply/catalog-images.json.
 */

require_once ABSPATH . 'wp-admin/includes/image.php';
require_once ABSPATH . 'wp-admin/includes/file.php';

$urumi_map = array(
	'URS-JRN-001' => 'field-notes-journal',
	'URS-MUG-001' => 'everyday-ceramic-mug',
	'URS-ORG-001' => 'arc-desk-organizer',
	'URS-TOT-001' => 'canvas-utility-tote',
	'URS-POU-001' => 'travel-cable-pouch',
	'URS-BTL-001' => 'studio-bottle',
	'URS-PEN-001' => 'modular-pen-set',
	'URS-MAT-001' => 'soft-grid-desk-mat',
	'URS-PCK-001' => 'weekend-packing-cubes',
	'URS-SLV-001' => 'pocket-tech-sleeve',
	'URS-TRY-001' => 'stoneware-catchall-tray',
	'URS-CRY-001' => 'daily-carry-pouch',
);

$urumi_theme = get_template_directory();
$urumi_src   = $urumi_theme . '/assets/products';
$urumi_up    = wp_upload_dir();
$urumi_dir   = trailingslashit( $urumi_up['basedir'] ) . 'urumi-supply';
$urumi_url   = trailingslashit( $urumi_up['baseurl'] ) . 'urumi-supply';

if ( ! is_dir( $urumi_dir ) ) {
	wp_mkdir_p( $urumi_dir );
}

$urumi_manifest = array();

foreach ( $urumi_map as $urumi_sku => $urumi_slug ) {
	$urumi_file = $urumi_slug . '.svg';
	$urumi_from = trailingslashit( $urumi_src ) . $urumi_file;
	$urumi_to   = trailingslashit( $urumi_dir ) . $urumi_file;

	if ( ! file_exists( $urumi_from ) ) {
		fwrite( STDERR, "urumi: missing illustration {$urumi_from}\n" );
		continue;
	}

	if ( ! file_exists( $urumi_to ) || filesize( $urumi_to ) !== filesize( $urumi_from ) ) {
		copy( $urumi_from, $urumi_to );
	}

	$urumi_existing = get_posts(
		array(
			'post_type'      => 'attachment',
			'post_status'    => 'inherit',
			'posts_per_page' => 1,
			'fields'         => 'ids',
			'meta_key'       => '_urumi_sku',
			'meta_value'     => $urumi_sku,
		)
	);

	if ( $urumi_existing ) {
		$urumi_id = (int) $urumi_existing[0];
		update_attached_file( $urumi_id, 'urumi-supply/' . $urumi_file );
	} else {
		$urumi_id = wp_insert_attachment(
			array(
				'guid'           => $urumi_url . '/' . $urumi_file,
				'post_mime_type' => 'image/svg+xml',
				'post_title'     => ucwords( str_replace( '-', ' ', $urumi_slug ) ),
				'post_content'   => '',
				'post_excerpt'   => '',
				'post_status'    => 'inherit',
			),
			$urumi_to
		);

		if ( is_wp_error( $urumi_id ) || ! $urumi_id ) {
			fwrite( STDERR, "urumi: could not attach {$urumi_file}\n" );
			continue;
		}

		update_post_meta( $urumi_id, '_urumi_sku', $urumi_sku );
		update_post_meta( $urumi_id, '_wp_attachment_image_alt', ucwords( str_replace( '-', ' ', $urumi_slug ) ) );
	}

	// WordPress cannot read the dimensions of an SVG, so record them manually.
	// Without this the rendered <img> tag carries a 1x1 placeholder size.
	wp_update_attachment_metadata(
		$urumi_id,
		array(
			'width'      => 800,
			'height'     => 1000,
			'file'       => 'urumi-supply/' . $urumi_file,
			'sizes'      => array(),
			'image_meta' => array(),
		)
	);

	$urumi_manifest[ $urumi_sku ] = (int) $urumi_id;
}

file_put_contents(
	trailingslashit( $urumi_dir ) . 'catalog-images.json',
	wp_json_encode( $urumi_manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES )
);

// --- Storefront pages -------------------------------------------------------
// WooCommerce creates the Cart and Checkout pages with the block markup. The
// theme is a classic template theme, so switch both pages to the matching
// shortcodes and let the theme render them.
$urumi_pages = array(
	'cart'     => '[woocommerce_cart]',
	'checkout' => '[woocommerce_checkout]',
);

foreach ( $urumi_pages as $urumi_page => $urumi_content ) {
	$urumi_page_id = wc_get_page_id( $urumi_page );

	if ( $urumi_page_id < 1 ) {
		fwrite( STDERR, "urumi: page {$urumi_page} not found\n" );
		continue;
	}

	$urumi_post = get_post( $urumi_page_id );

	if ( ! $urumi_post || $urumi_post->post_content === $urumi_content ) {
		continue;
	}

	wp_update_post(
		array(
			'ID'           => $urumi_page_id,
			'post_content' => $urumi_content,
		)
	);
	fwrite( STDERR, "urumi: switched {$urumi_page} page to the classic template\n" );
}

// --- Store settings ---------------------------------------------------------
// A fresh WooCommerce install has no payment gateway and no shipping method,
// which makes the checkout unusable. The demo store ships with cash on
// delivery and free shipping over $60 (the amount announced in the header).
update_option(
	'woocommerce_cod_settings',
	array(
		'enabled'            => 'yes',
		'title'              => 'Cash on delivery',
		'description'        => 'Pay with cash when your order arrives.',
		'instructions'       => '',
		'enable_for_methods' => array(),
		'enable_for_virtual' => 'yes',
	)
);

if ( ! class_exists( 'WC_Shipping_Zones' ) ) {
	fwrite( STDERR, "urumi: WooCommerce shipping classes unavailable\n" );
} else {
	$urumi_zone = false;

	foreach ( WC_Shipping_Zones::get_shipping_zones() as $urumi_candidate ) {
		if ( 'Urumi Supply' === $urumi_candidate->get_zone_name() ) {
			$urumi_zone = $urumi_candidate;
			break;
		}
	}

	if ( ! $urumi_zone ) {
		$urumi_zone = new WC_Shipping_Zone();
		$urumi_zone->set_zone_name( 'Urumi Supply' );
		$urumi_zone->set_zone_order( 1 );
		$urumi_zone->save();

		$urumi_zone->add_shipping_method( 'free_shipping' );
		$urumi_zone->save();
	}

	foreach ( $urumi_zone->get_shipping_methods() as $urumi_method ) {
		if ( 'free_shipping' !== $urumi_method->id ) {
			continue;
		}

		update_option(
			$urumi_method->get_instance_option_key(),
			array(
				'requires'          => 'min_amount',
				'min_amount'        => 60,
				'ignore_discounts'  => 'no',
			)
		);
	}
}

update_option( 'woocommerce_default_country', 'US:NY' );

echo 'URUMI_MANIFEST:' . wp_json_encode( $urumi_manifest ) . "\n";
