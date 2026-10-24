<?php
/**
 * Product card used on the front page and archive grids.
 *
 * @package Urumi_Supply
 */

global $product;

// The card is rendered inside a WP_Query loop as well as from WooCommerce's
// own loop, so resolve the product from the current post when needed.
if ( ! $product instanceof WC_Product ) {
	$product = wc_get_product( get_the_ID() );
}

if ( ! $product instanceof WC_Product ) {
	return;
}

$stock_tone = urumi_supply_stock_tone( $product );
$featured   = urumi_supply_is_featured( $product );
?>
<article <?php wc_product_class( 'product-card', $product ); ?>>
	<a class="product-card-media" href="<?php the_permalink(); ?>">
		<?php
		echo wp_kses_post(
			$product->get_image(
				'urumi-product-card',
				array(
					'class'   => 'product-card-image',
					'loading' => 'lazy',
				)
			)
		);
		?>
		<?php if ( $featured ) : ?>
			<span class="product-flag"><?php esc_html_e( 'Featured', 'urumi-supply' ); ?></span>
		<?php endif; ?>
		<span class="stock-flag <?php echo esc_attr( $stock_tone ); ?>">
			<?php echo esc_html( urumi_supply_stock_label( $product ) ); ?>
		</span>
	</a>

	<div class="product-card-body">
		<h3 class="product-card-title">
			<a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
		</h3>
		<div class="product-card-meta">
			<span class="product-price"><?php echo wp_kses_post( $product->get_price_html() ); ?></span>
			<?php if ( $product->get_sku() ) : ?>
				<span class="product-sku-inline"><?php echo esc_html( $product->get_sku() ); ?></span>
			<?php endif; ?>
		</div>
	</div>
</article>
