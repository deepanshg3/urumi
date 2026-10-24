<?php
/**
 * Shop loop product card.
 *
 * Overrides WooCommerce's default loop item so the storefront grid matches the
 * editorial look of the rest of the theme (stock flag, SKU, quieter chrome).
 *
 * @package Urumi_Supply
 */

global $product;

if ( empty( $product ) || ! $product->is_visible() ) {
	return;
}

$stock_tone = urumi_supply_stock_tone( $product );
$featured   = urumi_supply_is_featured( $product );
?>
<li <?php wc_product_class( 'product-card is-loop', $product ); ?>>
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
		<h2 class="product-card-title">
			<a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
		</h2>
		<div class="product-card-meta">
			<span class="product-price"><?php echo wp_kses_post( $product->get_price_html() ); ?></span>
			<?php if ( $product->get_sku() ) : ?>
				<span class="product-sku-inline"><?php echo esc_html( $product->get_sku() ); ?></span>
			<?php endif; ?>
		</div>
	</div>
</li>
