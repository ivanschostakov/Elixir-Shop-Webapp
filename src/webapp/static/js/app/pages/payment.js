import { showLoader, hideLoader } from "../ui/loader.js";
import { hideMainButton, isTelegramApp, showBackButton, showMainButton } from "../ui/telegram.js";
import { navigateTo } from "../router.js";
import { saveCart, state } from "../state.js";
import {
    cartPageEl,
    checkoutPageEl,
    contactPageEl,
    detailEl,
    headerTitle,
    listEl,
    navBottomEl,
    orderDetailEl,
    ordersPageEl,
    paymentPageEl,
    processPaymentEl,
    profilePageEl,
    searchBtnEl,
    toolbarEl,
} from "./constants.js";
import { apiPost } from "../../services/api.js";

const PAYMENT_NOTES = {
    sbp: "Оплата пройдет через IntellectMoney. Мы покажем QR-код, а подтверждение пройдет автоматически.",
    later: "После оформления заказа менеджер свяжется с вами для подтверждения оплаты.",
};

const PAYMENT_ERROR_MESSAGES = new Map([
    ["contact_info is required", "Заполните контактные данные перед оплатой."],
    ["Cart is empty", "Корзина пуста. Вернитесь к оформлению заказа."],
    ["Unsupported delivery service", "Выберите доступный способ доставки."],
    ["Unsupported payment method", "Этот способ оплаты сейчас недоступен."],
    ["Price must be greater than 0", "Сумма заказа должна быть больше нуля."],
    ["Order not found", "Заказ не найден."],
    ["Failed to initialize SBP payment", "Не удалось инициализировать оплату по СБП. Попробуйте еще раз чуть позже."],
]);


function readJson(key, fallback = null) {
    try {
        return JSON.parse(sessionStorage.getItem(key) || "null") ?? fallback;
    } catch {
        return fallback;
    }
}


function getSelectedMethod() {
    const checked = paymentPageEl?.querySelector('input[name="payment_method"]:checked');
    return checked ? checked.value : "later";
}


function toNumber(value) {
    if (value == null) return 0;
    const parsed = Number(String(value).replace(",", "."));
    return Number.isFinite(parsed) ? parsed : 0;
}


function formatMoney(value) {
    const amount = toNumber(value);
    return `${amount.toFixed(2)} ₽`;
}


function resolveDeliverySum(selectedDelivery, selectedDeliveryService) {
    const service = String(selectedDeliveryService || "").toLowerCase();

    if (service === "yandex") {
        let costRub = 0;
        const raw = localStorage.getItem("yandex_delivery_cost_rub") ?? sessionStorage.getItem("yandex_delivery_cost_rub");
        if (raw != null) {
            const parsed = Number(raw);
            if (Number.isFinite(parsed) && parsed > 0) costRub = Math.round(parsed);
        }

        if (!costRub && selectedDelivery && typeof selectedDelivery === "object") {
            const priceCandidate =
                selectedDelivery?.calc?.price?.pricing_total ??
                selectedDelivery?.calc?.price?.pricing ??
                selectedDelivery?.calc?.pricing_total ??
                selectedDelivery?.calc?.pricing ??
                selectedDelivery?.delivery_sum ??
                null;
            if (priceCandidate != null) {
                const match = String(priceCandidate).trim().match(/(\d+(?:[.,]\d+)?)/);
                if (match) {
                    const parsed = Number(match[1].replace(",", "."));
                    if (Number.isFinite(parsed) && parsed > 0) costRub = Math.round(parsed);
                }
            }
        }

        return costRub;
    }

    if (service === "cdek") {
        const candidates = [
            selectedDelivery?.delivery_sum,
            selectedDelivery?.tariff?.delivery_sum,
            sessionStorage.getItem("delivery_sum"),
        ];
        for (const candidate of candidates) {
            const parsed = Number(String(candidate ?? "").replace(",", "."));
            if (Number.isFinite(parsed) && parsed >= 0) return parsed;
        }
    }

    const fallback = Number(String(selectedDelivery?.delivery_sum ?? sessionStorage.getItem("delivery_sum") ?? 0).replace(",", "."));
    return Number.isFinite(fallback) ? fallback : 0;
}


function ensureDeliverySum(selectedDelivery, selectedDeliveryService) {
    const costRub = resolveDeliverySum(selectedDelivery, selectedDeliveryService);
    const nextDelivery = selectedDelivery && typeof selectedDelivery === "object" ? { ...selectedDelivery } : {};
    nextDelivery.delivery_sum = costRub;
    sessionStorage.setItem("delivery_sum", String(costRub));
    sessionStorage.setItem("selected_delivery", JSON.stringify(nextDelivery));
    return nextDelivery;
}


function getReadablePaymentError(error) {
    const rawMessage = String(error?.message || "").trim();
    const status = Number(error?.status || 0);

    if (PAYMENT_ERROR_MESSAGES.has(rawMessage)) {
        return PAYMENT_ERROR_MESSAGES.get(rawMessage);
    }

    if (rawMessage.includes("У вас уже есть активный заказ")) {
        return rawMessage;
    }

    const normalized = rawMessage.toLowerCase();
    if (normalized.includes("intellectmoney") || normalized.includes("sbp")) {
        return "Не удалось инициализировать оплату по СБП. Попробуйте еще раз чуть позже.";
    }

    if (status >= 500) {
        return "Не удалось создать оплату прямо сейчас. Попробуйте еще раз чуть позже.";
    }

    return rawMessage || "Не удалось создать оплату. Попробуйте еще раз.";
}


function clearCheckoutState() {
    state.cart = {};
    saveCart();
    [
        "checkout_data",
        "selected_delivery",
        "selected_delivery_service",
        "contact_info",
        "payment_commentary",
        "delivery_sum",
        "promocode",
        "promocode_data",
        "sbp_payment_state",
    ].forEach((key) => sessionStorage.removeItem(key));
}


function getSelectedDeliveryService() {
    return sessionStorage.getItem("selected_delivery_service") || "CDEK";
}


function renderPaymentMarkup() {
    const checkoutData = readJson("checkout_data", {});
    const selectedDeliveryService = getSelectedDeliveryService();
    const delivery = ensureDeliverySum(readJson("selected_delivery", {}), selectedDeliveryService);
    const commentary = (sessionStorage.getItem("payment_commentary") || "").trim();
    const subtotal = toNumber(checkoutData?.total);
    const deliverySum = toNumber(delivery?.delivery_sum ?? 0);
    const total = subtotal + deliverySum;

    paymentPageEl.innerHTML = `
        <div class="process-card">
            <h2 class="process-title">Выберите способ оплаты</h2>
            <p class="process-text">Выберите удобный способ оплаты для заказа.</p>

            <div class="process-order-box">
                <div class="process-order-label">Сумма заказа</div>
                <div class="process-order-value">${formatMoney(total)}</div>
                <div class="process-hint">Товары: ${formatMoney(subtotal)}${deliverySum > 0 ? ` • Доставка: ${formatMoney(deliverySum)}` : ""}</div>
            </div>

            <div id="payment-methods" class="payment-methods">
                <label class="payment-method payment-method--active">
                    <input type="radio" name="payment_method" value="later" checked />
                    <span>Оплатить позже</span>
                </label>
            </div>

            <p id="payment-method-note" class="process-text">${PAYMENT_NOTES.later}</p>
            ${commentary ? `<p class="process-hint">Комментарий к заказу: ${escapeHtml(commentary)}</p>` : ""}
        </div>
    `;

    const methodsContainer = document.getElementById("payment-methods");
    const noteEl = document.getElementById("payment-method-note");
    methodsContainer?.addEventListener("change", (event) => {
        if (event.target?.name !== "payment_method") return;
        methodsContainer.querySelectorAll(".payment-method").forEach((label) => {
            const input = label.querySelector('input[type="radio"]');
            label.classList.toggle("payment-method--active", Boolean(input?.checked));
        });
        const nextMethod = getSelectedMethod();
        if (noteEl) noteEl.textContent = PAYMENT_NOTES[nextMethod] || "";
    });
}


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


async function handlePaymentSubmit() {
    const contactInfo = readJson("contact_info");
    const checkoutData = readJson("checkout_data");
    const rawDelivery = readJson("selected_delivery");
    const selectedDeliveryService = getSelectedDeliveryService();
    const paymentMethod = getSelectedMethod();

    if (!contactInfo) {
        alert("Контактные данные не найдены. Вернитесь назад и заполните форму.");
        navigateTo("/contact");
        return;
    }

    if (!checkoutData) {
        alert("Корзина пуста. Вернитесь к оформлению.");
        navigateTo("/cart");
        return;
    }
    if (!rawDelivery || typeof rawDelivery !== "object") {
        alert("Сначала выберите доставку.");
        navigateTo("/checkout");
        return;
    }
    const selectedDelivery = ensureDeliverySum(rawDelivery, selectedDeliveryService);
    const tg = state.telegram;
    const userId =
        sessionStorage.getItem("tg_user_id") ||
        (tg?.initDataUnsafe?.user?.id != null ? String(tg.initDataUnsafe.user.id) : null);

    const payload = {
        user_id: userId,
        tg_nick: tg?.initDataUnsafe?.user?.username || null,
        contact_info: contactInfo,
        checkout_data: checkoutData,
        selected_delivery: selectedDelivery,
        selected_delivery_service: selectedDeliveryService,
        payment_method: paymentMethod,
        commentary: (sessionStorage.getItem("payment_commentary") || "").trim() || null,
        promocode: readJson("promocode"),
        source: "telegram",
    };

    try {
        showLoader();
        const result = await apiPost("/payments/create", payload);
        if (paymentMethod === "later") {
            clearCheckoutState();
            navigateTo(`/payment-process?order_id=${encodeURIComponent(String(result.order_number))}&mode=later_success`);
            return;
        }

        sessionStorage.setItem("sbp_payment_state", JSON.stringify(result || {}));
        navigateTo(`/payment-process?order_id=${encodeURIComponent(String(result.order_number))}`);
    } catch (error) {
        console.error("Payment creation failed:", error);
        alert(getReadablePaymentError(error));
    } finally {
        hideLoader();
    }
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

function exitPaymentPageToHome() {
    hidePaymentFlowViews({ clearMarkup: true });
    navigateTo("/");
}


export async function renderPaymentPage() {
    if (!paymentPageEl) return;

    const contactInfo = readJson("contact_info");
    const checkoutData = readJson("checkout_data");
    const selectedDelivery = readJson("selected_delivery");
    if (!contactInfo) {
        hidePaymentFlowViews({ clearMarkup: true });
        navigateTo("/contact");
        return;
    }
    if (!checkoutData || !selectedDelivery) {
        hidePaymentFlowViews({ clearMarkup: true });
        navigateTo("/checkout");
        return;
    }
    toolbarEl.style.display = "none";
    listEl.style.display = "none";
    detailEl.style.display = "none";
    cartPageEl.style.display = "none";
    checkoutPageEl.style.display = "none";
    contactPageEl.style.display = "none";
    paymentPageEl.style.display = "block";
    processPaymentEl.style.display = "none";
    profilePageEl.style.display = "none";
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "none";
    searchBtnEl.style.display = "none";
    navBottomEl.style.display = "none";
    headerTitle.textContent = "Оплата";

    renderPaymentMarkup();

    if (isTelegramApp()) {
        showBackButton(exitPaymentPageToHome);
        showMainButton("Продолжить", handlePaymentSubmit);
    } else {
        hideMainButton();
    }
}
