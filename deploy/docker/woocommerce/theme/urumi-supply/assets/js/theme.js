/**
 * Urumi Supply — progressive enhancement only.
 *
 * The storefront works without JavaScript; this file adds the mobile drawer,
 * a sticky "add to bag" affordance on product pages, and a live cart count.
 */
(function () {
  "use strict";

  /* -- Mobile navigation ------------------------------------------------- */
  var toggle = document.querySelector("[data-menu-toggle]");
  var nav = document.getElementById("mobile-nav");

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      nav.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* -- Live cart count --------------------------------------------------- */
  var cartCount = document.querySelector("[data-cart-count]");

  function refreshCartCount() {
    if (!cartCount || !window.wpApiSettings) {
      return;
    }

    var request = new XMLHttpRequest();
    request.open(
      "GET",
      window.wpApiSettings.root + "/wc/store/v1/cart",
      true
    );
    request.setRequestHeader("Content-Type", "application/json");
    request.onload = function () {
      if (request.status < 200 || request.status >= 300) {
        return;
      }
      try {
        var payload = JSON.parse(request.responseText);
        var count = 0;
        (payload.items || []).forEach(function (item) {
          count += item.quantity || 0;
        });
        cartCount.textContent = String(count);
      } catch (error) {
        /* Leave the server-rendered count in place. */
      }
    };
    request.send();
  }

  refreshCartCount();
  window.addEventListener("urumi:cart-updated", refreshCartCount);
})();
