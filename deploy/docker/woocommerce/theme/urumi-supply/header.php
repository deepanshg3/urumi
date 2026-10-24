<?php
/**
 * Site header.
 *
 * @package Urumi_Supply
 */

?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
	<meta charset="<?php bloginfo( 'charset' ); ?>">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>

<a class="skip-link" href="#main"><?php esc_html_e( 'Skip to content', 'urumi-supply' ); ?></a>

<div class="announce">
	<div class="shell announce-inner">
		<p><?php esc_html_e( 'Free shipping over $60 · Ships in 1–2 business days', 'urumi-supply' ); ?></p>
		<p class="announce-meta"><?php esc_html_e( 'Urumi Supply — demo storefront', 'urumi-supply' ); ?></p>
	</div>
</div>

<header class="site-header" id="site-header">
	<div class="shell header-inner">
		<div class="header-brand">
			<a class="brand" href="<?php echo esc_url( home_url( '/' ) ); ?>" rel="home">
				<span class="brand-mark" aria-hidden="true">
					<svg width="20" height="20" viewBox="0 0 32 32" fill="none">
						<path d="M9.5 7.5v10.2a6.5 6.5 0 0 0 13 0V7.5" stroke="#ffffff" stroke-width="2.6" stroke-linecap="round"/>
						<path d="M22.6 5.1c2.8.6 4.8 2.9 5.1 5.7-2.8.2-5.2-1.8-5.1-5.7Z" fill="#9CD3B7"/>
					</svg>
				</span>
				<span class="brand-text">
					<span class="brand-name"><?php bloginfo( 'name' ); ?></span>
					<span class="brand-sub"><?php bloginfo( 'description' ); ?></span>
				</span>
			</a>
		</div>

		<nav class="header-nav" aria-label="<?php esc_attr_e( 'Primary', 'urumi-supply' ); ?>">
			<?php urumi_supply_primary_menu(); ?>
		</nav>

		<div class="header-actions">
			<form class="header-search" role="search" method="get" action="<?php echo esc_url( wc_get_page_permalink( 'shop' ) ); ?>">
				<label class="visually-hidden" for="header-search-field"><?php esc_html_e( 'Search products', 'urumi-supply' ); ?></label>
				<input
					id="header-search-field"
					class="header-search-field"
					type="search"
					name="s"
					value="<?php echo esc_attr( get_search_query() ); ?>"
					placeholder="<?php esc_attr_e( 'Search products', 'urumi-supply' ); ?>"
				/>
				<button class="header-search-submit" type="submit">
					<span class="visually-hidden"><?php esc_html_e( 'Search', 'urumi-supply' ); ?></span>
					<svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
						<circle cx="9" cy="9" r="6" stroke="currentColor" stroke-width="1.8"/>
						<path d="m13.5 13.5 3.5 3.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
					</svg>
				</button>
			</form>

			<a class="header-action" href="<?php echo esc_url( wc_get_page_permalink( 'myaccount' ) ); ?>">
				<?php esc_html_e( 'Account', 'urumi-supply' ); ?>
			</a>
			<a class="header-action cart-link" href="<?php echo esc_url( wc_get_cart_url() ); ?>">
				<?php esc_html_e( 'Bag', 'urumi-supply' ); ?>
				<span class="cart-count" data-cart-count><?php echo esc_html( (string) urumi_supply_cart_count() ); ?></span>
			</a>
			<button class="menu-toggle" type="button" aria-expanded="false" aria-controls="mobile-nav" data-menu-toggle>
				<span class="visually-hidden"><?php esc_html_e( 'Toggle menu', 'urumi-supply' ); ?></span>
				<span class="menu-toggle-bar" aria-hidden="true"></span>
				<span class="menu-toggle-bar" aria-hidden="true"></span>
			</button>
		</div>
	</div>

	<div class="mobile-nav" id="mobile-nav" hidden>
		<?php urumi_supply_primary_menu(); ?>
		<form class="mobile-search" role="search" method="get" action="<?php echo esc_url( wc_get_page_permalink( 'shop' ) ); ?>">
			<label class="visually-hidden" for="mobile-search-field"><?php esc_html_e( 'Search products', 'urumi-supply' ); ?></label>
			<input
				id="mobile-search-field"
				class="header-search-field"
				type="search"
				name="s"
				value="<?php echo esc_attr( get_search_query() ); ?>"
				placeholder="<?php esc_attr_e( 'Search products', 'urumi-supply' ); ?>"
			/>
		</form>
		<a class="mobile-nav-link" href="<?php echo esc_url( wc_get_page_permalink( 'myaccount' ) ); ?>">
			<?php esc_html_e( 'Account', 'urumi-supply' ); ?>
		</a>
	</div>
</header>

<main id="main" class="site-main">
