import { renderFavouritesPage, renderHomePage } from "./pages/home.js";
import { renderProductDetailPage } from "./pages/product-detail.js";
import { renderCartPage } from "./pages/cart.js";
import { renderCheckoutPage } from "./pages/checkout.js";
import { renderContactPage } from "./pages/contact.js";
import { renderPaymentPage } from "./pages/payment.js";
import { renderProcessPaymentPage } from "./pages/process-payment.js";
import { paymentPageEl, processPaymentEl } from "./pages/constants.js";
import { setupBottomNav, updateBottomNavActive } from "./ui/nav-bottom.js";
import { renderProfilePage } from "./pages/profile.js";
import { renderOrdersPage } from "./pages/orders.js";
import { hideLoader, showLoader } from "./ui/loader.js";

function stripQuery(path) {
    const queryPos = path.indexOf("?");
    if (queryPos === -1) return path;
    return path.slice(0, queryPos);
}

function parseProductPath(path) {
    const rawId = path.split("/product/")[1] || "";
    return stripQuery(rawId).split("/")[0];
}

const routes = [
    { match: (path) => path === "/" || path === "", action: renderHomePage },
    { match: (path) => path.startsWith("/product/"), action: (path) => renderProductDetailPage(parseProductPath(path)) },
    { match: (path) => path === "/cart", action: renderCartPage },
    { match: (path) => path === "/checkout", action: renderCheckoutPage },
    { match: (path) => path === "/contact", action: renderContactPage },
    { match: (path) => path === "/payment", action: renderPaymentPage },
    { match: (path) => path === "/payment-process", action: renderProcessPaymentPage },
    { match: (path) => path === "/favourites", action: renderFavouritesPage },
    { match: (path) => path === "/profile", action: renderProfilePage },
    { match: (path) => path === "/orders", action: renderOrdersPage },
];

function getCurrentPath() {
    const rawHash = window.location.hash || "";
    const path = rawHash.replace(/^#/, "");
    if (!path) return "/";
    return stripQuery(path);
}

function hidePaymentFlowViews({ clearMarkup = false } = {}) {
    if (paymentPageEl) {
        paymentPageEl.style.display = "none";
        if (clearMarkup) paymentPageEl.innerHTML = "";
    }
    if (processPaymentEl) {
        processPaymentEl.style.display = "none";
        if (clearMarkup) processPaymentEl.innerHTML = "";
    }
}

export async function renderCurrentPath() {
    showLoader();
    const currentPath = getCurrentPath();
    if (currentPath !== "/payment" && currentPath !== "/payment-process") {
        hidePaymentFlowViews({ clearMarkup: true });
    }
    for (const route of routes) {
        if (!route.match(currentPath)) continue;
        await route.action(currentPath);
        if (!currentPath.includes("checkout")) hideLoader();
        return;
    }
    await renderHomePage();
    hideLoader();
}

export function navigateTo(path) {
    setupBottomNav();
    const normalized = path.startsWith("/") ? path : `/${path}`;
    updateBottomNavActive(normalized);
    const targetHash = `#${normalized}`;
    if (window.location.hash === targetHash) return;
    window.location.hash = normalized;
}

export function enablePopstate() { window.addEventListener("hashchange", () => void renderCurrentPath()); }
