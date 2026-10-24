<?php
/**
 * Urumi Supply theme setup.
 *
 * @package Urumi_Supply
 */

declare( strict_types = 1 );

define( 'URUMI_SUPPLY_VERSION', '1.0.0' );
define( 'URUMI_SUPPLY_DIR', get_template_directory() );
define( 'URUMI_SUPPLY_URI', get_template_directory_uri() );

/**
 * Theme supports and image sizes.
 */
function urumi_supply_setup(): void {
	load_theme_textdomain( 'urumi-supply', URUMI_SUPPLY_DIR . '/languages' );

	add_theme_support( 'automatic-feed-links' );
	add_theme_support( 'title-tag' );
	add_theme_support( 'post-thumbnails' );
	add_theme_support( 'responsive-embeds' );
	add_theme_support( 'align-wide' );
	add_theme_support( 'wp-block-styles' );
	add_theme_support( 'editor-styles' );
	add_editor_style( 'assets/css/theme.css' );

	add_theme_support(
		'html5',
		array( 'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'style', 'script' )
	);

	add_theme_support(
		'custom-logo',
		array(
			'height'      => 64,
			'width'       => 220,
			'flex-height' => true,
			'flex-width'  => true,
		)
	);

	add_theme_support(
		'woocommerce',
		array(
			'thumbnail_image_width' => 600,
			'single_image_width'    => 1200,
			'product_grid'          => array(
				'default_rows'    => 3,
				'min_rows'        => 1,
				'default_columns' => 3,
				'min_columns'     => 2,
				'max_columns'     => 4,
			),
		)
	);

	add_theme_support( 'wc-product-gallery-zoom' );
	add_theme_support( 'wc-product-gallery-lightbox' );
	add_theme_support( 'wc-product-gallery-slider' );

	register_nav_menus(
		array(
			'primary' => __( 'Primary menu', 'urumi-supply' ),
			'footer'  => __( 'Footer menu', 'urumi-supply' ),
		)
	);

	add_image_size( 'urumi-product-card', 800, 1000, true );
	add_image_size( 'urumi-hero', 1600, 1200, true );
}
add_action( 'after_setup_theme', 'urumi_supply_setup' );

/**
 * Front-end assets.
 */
function urumi_supply_assets(): void {
	wp_enqueue_style(
		'urumi-supply-fonts',
		URUMI_SUPPLY_URI . '/assets/css/fonts.css',
		array(),
		URUMI_SUPPLY_VERSION
	);

	wp_enqueue_style(
		'urumi-supply',
		URUMI_SUPPLY_URI . '/assets/css/theme.css',
		array( 'urumi-supply-fonts' ),
		URUMI_SUPPLY_VERSION
	);

	wp_enqueue_script(
		'urumi-supply',
		URUMI_SUPPLY_URI . '/assets/js/theme.js',
		array(),
		URUMI_SUPPLY_VERSION,
		true
	);
}
add_action( 'wp_enqueue_scripts', 'urumi_supply_assets' );

/**
 * Preload the two primary font files so the first paint is not delayed.
 */
function urumi_supply_preload_fonts(): void {
	$fonts = array(
		'/assets/fonts/inter-latin.woff2',
		'/assets/fonts/dmsans-latin.woff2',
	);

	foreach ( $fonts as $font ) {
		printf(
			'<link rel="preload" href="%s" as="font" type="font/woff2" crossorigin>' . "\n",
			esc_url( URUMI_SUPPLY_URI . $font )
		);
	}
}
add_action( 'wp_head', 'urumi_supply_preload_fonts', 1 );

/**
 * Widget areas.
 */
function urumi_supply_widgets(): void {
	register_sidebar(
		array(
			'name'          => __( 'Shop sidebar', 'urumi-supply' ),
			'id'            => 'shop-sidebar',
			'description'   => __( 'Shown on the shop and product archive pages.', 'urumi-supply' ),
			'before_widget' => '<section id="%1$s" class="widget %2$s">',
			'after_widget'  => '</section>',
			'before_title'  => '<h2 class="widget-title">',
			'after_title'   => '</h2>',
		)
	);
}
add_action( 'widgets_init', 'urumi_supply_widgets' );

/**
 * The storefront is a focused, single-column shop: drop the WooCommerce
 * sidebar and let the grid use the full canvas.
 */
add_filter( 'woocommerce_enable_sidebar', '__return_false' );
remove_action( 'woocommerce_sidebar', 'woocommerce_get_sidebar', 10 );

/**
 * Body classes used by the stylesheet.
 *
 * @param string[] $classes Existing classes.
 * @return string[]
 */
function urumi_supply_body_classes( array $classes ): array {
	$classes[] = 'urumi';

	if ( is_front_page() ) {
		$classes[] = 'is-front';
	}

	if ( ! is_active_sidebar( 'shop-sidebar' ) ) {
		$classes[] = 'no-sidebar';
	}

	return $classes;
}
add_filter( 'body_class', 'urumi_supply_body_classes' );

/**
 * The announcement bar is rendered by the theme, so remove the WooCommerce
 * demo notice that otherwise shows up on every page of a fresh install.
 */
add_filter( 'woocommerce_demo_store', '__return_false' );

/**
 * Mark SVG illustrations so the stylesheet can style them.
 *
 * WordPress cannot read the pixel size of an SVG, so the attachment metadata
 * is written by scripts/woo_seed_images.php; this filter only flags the tag.
 *
 * @param array<string, string> $attributes Image attributes.
 * @param WP_Post               $attachment  The attachment.
 * @return array<string, string>
 */
function urumi_supply_svg_image_attributes( array $attributes, WP_Post $attachment ): array {
	if ( 'image/svg+xml' !== $attachment->post_mime_type ) {
		return $attributes;
	}

	$attributes['class'] = trim( ( $attributes['class'] ?? '' ) . ' is-svg' );

	return $attributes;
}
add_filter( 'wp_get_attachment_image_attributes', 'urumi_supply_svg_image_attributes', 10, 2 );

/**
 * Number of products per shop page.
 */
function urumi_supply_products_per_page(): int {
	return 12;
}
add_filter( 'loop_shop_per_page', 'urumi_supply_products_per_page', 20 );

/**
 * Product columns on the shop grid.
 */
function urumi_supply_loop_columns(): int {
	return 3;
}
add_filter( 'loop_shop_columns', 'urumi_supply_loop_columns', 20 );

/**
 * A calmer "added to cart" message that matches the editorial tone.
 */
function urumi_supply_cart_message(): void {
	if ( function_exists( 'wc_add_notice' ) && ! wc_get_notices( 'success' ) ) {
		wc_add_notice( __( 'Added to your bag.', 'urumi-supply' ), 'success' );
	}
}
add_action( 'woocommerce_after_add_to_cart_form', 'urumi_supply_cart_message', 5 );

/**
 * Show the SKU under the product title on the single product page.
 */
function urumi_supply_single_meta(): void {
	global $product;

	if ( ! $product || ! $product->get_sku() ) {
		return;
	}

	echo '<p class="product-sku">' . esc_html__( 'SKU', 'urumi-supply' ) . ' <code>' . esc_html( $product->get_sku() ) . '</code></p>';
}
add_action( 'woocommerce_product_meta_start', 'urumi_supply_single_meta' );

/**
 * Primary navigation, with a sensible fallback when no menu is assigned.
 */
function urumi_supply_primary_menu(): void {
	if ( has_nav_menu( 'primary' ) ) {
		wp_nav_menu(
			array(
				'theme_location' => 'primary',
				'container'      => false,
				'menu_class'     => 'menu',
				'depth'          => 1,
			)
		);
		return;
	}

	$fallback = array(
		__( 'Shop all', 'urumi-supply' )     => wc_get_page_permalink( 'shop' ),
		__( 'Best sellers', 'urumi-supply' ) => add_query_arg( 'orderby', 'popularity', wc_get_page_permalink( 'shop' ) ),
		__( 'Cart', 'urumi-supply' )         => wc_get_cart_url(),
	);

	echo '<ul class="menu">';
	foreach ( $fallback as $label => $url ) {
		printf( '<li class="menu-item"><a href="%s">%s</a></li>', esc_url( $url ), esc_html( $label ) );
	}
	echo '</ul>';
}

/**
 * Small helper: the number of items in the cart, used by the header badge.
 */
function urumi_supply_cart_count(): int {
	if ( ! function_exists( 'WC' ) || ! WC()->cart ) {
		return 0;
	}

	return (int) WC()->cart->get_cart_contents_count();
}

/**
 * Helper: stock label for a product, used by the product cards.
 *
 * @param WC_Product $product Product instance.
 * @return string
 */
function urumi_supply_stock_label( WC_Product $product ): string {
	if ( ! $product->is_in_stock() ) {
		return __( 'Out of stock', 'urumi-supply' );
	}

	if ( $product->managing_stock() && $product->get_stock_quantity() !== null ) {
		$quantity = (int) $product->get_stock_quantity();

		if ( $quantity <= 5 ) {
			return sprintf(
				/* translators: %d: remaining units. */
				__( 'Only %d left', 'urumi-supply' ),
				$quantity
			);
		}
	}

	return __( 'In stock', 'urumi-supply' );
}

/**
 * Helper: stock tone class used by the product cards.
 *
 * @param WC_Product $product Product instance.
 * @return string
 */
function urumi_supply_stock_tone( WC_Product $product ): string {
	if ( ! $product->is_in_stock() ) {
		return 'is-out';
	}

	if ( $product->managing_stock() && $product->get_stock_quantity() !== null && (int) $product->get_stock_quantity() <= 5 ) {
		return 'is-low';
	}

	return 'is-in';
}

/**
 * Expose the "featured" product flag on the card so the badge can be shown.
 *
 * @param WC_Product $product Product instance.
 * @return bool
 */
function urumi_supply_is_featured( WC_Product $product ): bool {
	return (bool) $product->get_meta( '_urumi_featured' );
}
