<?php
/**
 * Site footer.
 *
 * @package Urumi_Supply
 */

?>
</main>

<footer class="site-footer">
	<div class="shell footer-grid">
		<section class="footer-brand">
			<a class="brand brand-on-dark" href="<?php echo esc_url( home_url( '/' ) ); ?>" rel="home">
				<span class="brand-mark" aria-hidden="true">
					<svg width="20" height="20" viewBox="0 0 32 32" fill="none">
						<path d="M9.5 7.5v10.2a6.5 6.5 0 0 0 13 0V7.5" stroke="#ffffff" stroke-width="2.6" stroke-linecap="round"/>
						<path d="M22.6 5.1c2.8.6 4.8 2.9 5.1 5.7-2.8.2-5.2-1.8-5.1-5.7Z" fill="#9CD3B7"/>
					</svg>
				</span>
				<span class="brand-text">
					<span class="brand-name"><?php bloginfo( 'name' ); ?></span>
					<span class="brand-sub"><?php esc_html_e( 'Considered everyday goods', 'urumi-supply' ); ?></span>
				</span>
			</a>
			<p class="footer-note">
				<?php esc_html_e( 'A small, deliberately made collection of desk and carry goods. This storefront runs on WooCommerce behind the Urumi MCP Gateway.', 'urumi-supply' ); ?>
			</p>
		</section>

		<nav class="footer-col" aria-label="<?php esc_attr_e( 'Shop', 'urumi-supply' ); ?>">
			<h2 class="footer-heading"><?php esc_html_e( 'Shop', 'urumi-supply' ); ?></h2>
			<?php
			if ( has_nav_menu( 'footer' ) ) {
				wp_nav_menu(
					array(
						'theme_location' => 'footer',
						'container'      => false,
						'menu_class'     => 'footer-menu',
						'depth'          => 1,
					)
				);
			} else {
				echo '<ul class="footer-menu">';
				printf( '<li><a href="%s">%s</a></li>', esc_url( wc_get_page_permalink( 'shop' ) ), esc_html__( 'All products', 'urumi-supply' ) );
				printf( '<li><a href="%s">%s</a></li>', esc_url( wc_get_cart_url() ), esc_html__( 'Your bag', 'urumi-supply' ) );
				printf( '<li><a href="%s">%s</a></li>', esc_url( wc_get_page_permalink( 'myaccount' ) ), esc_html__( 'Your account', 'urumi-supply' ) );
				echo '</ul>';
			}
			?>
		</nav>

		<section class="footer-col">
			<h2 class="footer-heading"><?php esc_html_e( 'Care', 'urumi-supply' ); ?></h2>
			<ul class="footer-menu">
				<li><?php esc_html_e( 'Free shipping over $60', 'urumi-supply' ); ?></li>
				<li><?php esc_html_e( '30-day returns', 'urumi-supply' ); ?></li>
				<li><?php esc_html_e( 'Ships in 1–2 business days', 'urumi-supply' ); ?></li>
			</ul>
		</section>

		<section class="footer-col footer-newsletter">
			<h2 class="footer-heading"><?php esc_html_e( 'Notes from the studio', 'urumi-supply' ); ?></h2>
			<p class="footer-note"><?php esc_html_e( 'Occasional updates on new pieces and restocks.', 'urumi-supply' ); ?></p>
			<?php
			if ( shortcode_exists( 'woocommerce_email_subscription_form' ) ) {
				echo do_shortcode( '[woocommerce_email_subscription_form]' );
			} elseif ( function_exists( 'wp_newsletter' ) ) {
				wp_newsletter();
			}
			?>
		</section>
	</div>

	<div class="shell footer-bottom">
		<p>&copy; <?php echo esc_html( gmdate( 'Y' ) ); ?> <?php bloginfo( 'name' ); ?>. <?php esc_html_e( 'Demo storefront for the Urumi MCP Gateway.', 'urumi-supply' ); ?></p>
		<p class="footer-meta"><?php esc_html_e( 'Powered by WooCommerce · Served through the Urumi MCP Gateway', 'urumi-supply' ); ?></p>
	</div>
</footer>

<?php wp_footer(); ?>
</body>
</html>
