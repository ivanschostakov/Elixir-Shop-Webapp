import { renderCurrentPath, enablePopstate } from "./router.js";
import { initSearchOverlay } from "./pages/search.js";
import { initCartBadge } from "./ui/cart-badge.js";
import { setupBottomNav } from "./ui/nav-bottom.js";

document.addEventListener("DOMContentLoaded", async () => {
    setupBottomNav();
    initCartBadge();
    initSearchOverlay();
    enablePopstate();
    await renderCurrentPath();
});
