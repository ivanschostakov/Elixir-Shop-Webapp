function readJson(storage, key, fallback) {
    const raw = storage.getItem(key);
    if (raw == null) return fallback;
    try { return JSON.parse(raw); } catch { return fallback; }
}

const persistedCart = readJson(localStorage, "cart", {});

export const state = {
    user: null,
    cart: persistedCart,
    checkout: readJson(sessionStorage, "checkout_data", null),
    delivery: readJson(sessionStorage, "selected_delivery", null),
    deliveryService: sessionStorage.getItem("selected_delivery_service") || null,
    contact: readJson(sessionStorage, "yookassa_contact_info", null),
    telegram: (typeof window !== "undefined" && window.Telegram?.WebApp) || null,
};

export function saveCart() {
    localStorage.setItem("cart", JSON.stringify(state.cart));
    window.dispatchEvent(new CustomEvent("cart:updated"));
}

export function setCheckoutData(data) {
    state.checkout = data;
    sessionStorage.setItem("checkout_data", JSON.stringify(data));
}

export function setDelivery(data) {
    state.delivery = data;
    sessionStorage.setItem("selected_delivery", JSON.stringify(data));
}

export function setDeliveryService(name) {
    state.deliveryService = name;
    sessionStorage.setItem("selected_delivery_service", name);
}

export function setContactInfo(data) {
    state.contact = data;
    sessionStorage.setItem("yookassa_contact_info", JSON.stringify(data));
}
