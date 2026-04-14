import { navigateTo } from "../router.js";

let bottomNavInitialized = false;

export function setupBottomNav() {
    if (bottomNavInitialized) return;
    bottomNavInitialized = true;
    const items = document.querySelectorAll(".bottom-nav__item");
    items.forEach((item) => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const route = item.dataset.route || "/";
            navigateTo(route);
        });
    });
}

export function updateBottomNavActive(normalizedPath) {
    const navItems = document.querySelectorAll(".bottom-nav__item");
    navItems.forEach((item) => {
        item.classList.remove("bottom-nav__item--active");
        if (`/${item.dataset.route}` !== normalizedPath) return;
        item.classList.add("bottom-nav__item--active");
    });
}

export function getCurrentPathFromHash() {
    const hash = window.location.hash || "#/";
    let path = hash.startsWith("#") ? hash.slice(1) : hash;
    if (!path.startsWith("/")) path = `/${path}`;
    return path;
}
