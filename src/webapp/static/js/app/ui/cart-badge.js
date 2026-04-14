import { state } from "../state.js";

let cartBadgeInitialized = false;

export function getCartItemCount(cart = state.cart) {
    if (!cart || typeof cart !== "object") return 0;
    let total = 0;
    for (const value of Object.values(cart)) {
        const quantity = Number(value);
        if (Number.isFinite(quantity) && quantity > 0) total += quantity;
    }
    return total;
}

export function updateCartBadge() {
    const badge = document.getElementById("cart-badge");
    if (!badge) return;
    const count = getCartItemCount();
    if (count <= 0) {
        badge.classList.add("bottom-nav__badge--hidden");
        return;
    }
    badge.textContent = count > 99 ? "99+" : String(count);
    badge.classList.remove("bottom-nav__badge--hidden");
}

export function initCartBadge() {
    if (cartBadgeInitialized) return;
    cartBadgeInitialized = true;
    window.addEventListener("cart:updated", updateCartBadge);
    updateCartBadge();
}
