import { apiGet } from "../../services/api.js";
import { saveCart, state } from "../state.js";
import { hideMainButton, launchConfettiBurst, showBackButton, showMainButton } from "../ui/telegram.js";
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
import { navigateTo } from "../router.js";

let paymentPollTimer = null;
let lastRenderedSuccessKey = null;


function readJson(key, fallback = null) {
    try {
        return JSON.parse(sessionStorage.getItem(key) || "null") ?? fallback;
    } catch {
        return fallback;
    }
}


function stopPaymentPolling() {
    if (!paymentPollTimer) return;
    clearInterval(paymentPollTimer);
    paymentPollTimer = null;
}


function toNumber(value) {
    if (value == null) return 0;
    const parsed = Number(String(value).replace(",", "."));
    return Number.isFinite(parsed) ? parsed : 0;
}


function formatMoney(value) {
    return `${toNumber(value).toFixed(2)} ₽`;
}


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function getProcessParams() {
    const rawHash = window.location.hash || "";
    const queryPart = rawHash.includes("?") ? rawHash.slice(rawHash.indexOf("?") + 1) : "";
    const params = new URLSearchParams(queryPart);
    return {
        orderId: params.get("order_id") || "",
        result: params.get("result") || "",
        mode: params.get("mode") || "",
    };
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


function confirmCancelPayment() {
    return window.confirm("Если выйти сейчас, текущая попытка оплаты будет отменена, и вы вернетесь на главную. Продолжить?");
}


function cancelPendingPayment() {
    stopPaymentPolling();
    clearCheckoutState();
    hidePaymentFlowViews({ clearMarkup: true });
    navigateTo("/");
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


function exitProcessPaymentToHome() {
    stopPaymentPolling();
    hidePaymentFlowViews({ clearMarkup: true });
    navigateTo("/");
}


function renderBaseLayout(orderId) {
    toolbarEl.style.display = "none";
    listEl.style.display = "none";
    detailEl.style.display = "none";
    cartPageEl.style.display = "none";
    checkoutPageEl.style.display = "none";
    contactPageEl.style.display = "none";
    paymentPageEl.style.display = "none";
    processPaymentEl.style.display = "block";
    profilePageEl.style.display = "none";
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "none";
    searchBtnEl.style.display = "none";
    navBottomEl.style.display = "none";
    headerTitle.textContent = orderId ? `Заказ ${orderId}` : "Оплата";
}


function renderLaterSuccess(orderId) {
    stopPaymentPolling();
    renderBaseLayout(orderId);
    processPaymentEl.innerHTML = `
        <div class="process-card process-card--success">
            <div class="process-success-badge">Заказ создан</div>
            <h2 class="process-title">Спасибо за заказ</h2>
            <p class="process-text process-text--lead">Менеджер свяжется с вами для подтверждения оплаты.</p>
            <div class="process-success-note">
                <div class="process-success-note__title">Что дальше</div>
                <div class="process-success-note__text">Ничего дополнительно делать не нужно. Мы уже сохранили ваш заказ.</div>
            </div>
            <div class="process-order-box process-order-box--success">
                <div class="process-order-label">Номер заказа</div>
                <div class="process-order-value">${escapeHtml(orderId || "—")}</div>
            </div>
        </div>
    `;
    showMainButton("В главное меню", exitProcessPaymentToHome);
    showBackButton(exitProcessPaymentToHome);
    const successKey = `later:${orderId}`;
    if (lastRenderedSuccessKey !== successKey) {
        lastRenderedSuccessKey = successKey;
        try {
            launchConfettiBurst?.();
        } catch (error) {
            console.warn("Confetti error:", error);
        }
    }
}


function renderSbpPending(orderId, paymentState) {
    renderBaseLayout(orderId);
    const qrImage = paymentState?.qr_image
        ? `<img src="data:image/png;base64,${paymentState.qr_image}" alt="QR код СБП" style="max-width: 240px; width: 100%; border-radius: 12px;" />`
        : `<div class="process-order-box"><div class="process-hint">QR-код появится после инициализации платежа.</div></div>`;
    const qrLink = paymentState?.qr_url
        ? `<a href="${escapeHtml(paymentState.qr_url)}" target="_blank" rel="noopener noreferrer" class="process-order-value" style="font-size:0.95rem;">Открыть банк для оплаты</a>`
        : "";
    const invoiceId = paymentState?.invoice_id ? `<div class="process-hint">Счет: ${escapeHtml(paymentState.invoice_id)}</div>` : "";
    processPaymentEl.innerHTML = `
        <div class="process-card">
            <h2 class="process-title">Оплатите заказ</h2>
            <p class="process-text">Оплата проходит через IntellectMoney. Отсканируйте QR-код или откройте ссылку для оплаты.</p>
            <div class="process-order-box">
                <div class="process-order-label">Номер заказа</div>
                <div class="process-order-value">${escapeHtml(orderId || "—")}</div>
                ${invoiceId}
            </div>
            <div class="process-order-box">
                ${qrImage}
                ${qrLink ? `<div style="margin-top: 12px;">${qrLink}</div>` : ""}
            </div>
            <p class="process-hint">Мы проверяем оплату автоматически. Если уже оплатили, можно нажать кнопку ниже.</p>
            <button type="button" id="cancel-sbp-payment-btn" class="process-secondary-button">Отменить оплату</button>
        </div>
    `;
    processPaymentEl.querySelector("#cancel-sbp-payment-btn")?.addEventListener("click", () => {
        if (!confirmCancelPayment()) return;
        cancelPendingPayment();
    });
    showMainButton("Проверить оплату", () => void fetchAndRenderPaymentStatus(orderId, true));
    showBackButton(() => {
        if (!confirmCancelPayment()) return;
        cancelPendingPayment();
    });
}


function renderSbpFailure(orderId, paymentState) {
    stopPaymentPolling();
    renderBaseLayout(orderId);
    processPaymentEl.innerHTML = `
        <div class="process-card">
            <h2 class="process-title">Оплата не завершена</h2>
            <p class="process-text">${escapeHtml(paymentState?.payment_error || "Платеж не был завершен. Можно вернуться и попробовать снова.")}</p>
            <div class="process-order-box">
                <div class="process-order-label">Номер заказа</div>
                <div class="process-order-value">${escapeHtml(orderId || "—")}</div>
            </div>
        </div>
    `;
    showMainButton("Выбрать оплату", () => navigateTo(`/payment?order_id=${encodeURIComponent(orderId || "")}`));
    showBackButton(exitProcessPaymentToHome);
}


function renderSbpSuccess(orderId, paymentState) {
    stopPaymentPolling();
    renderBaseLayout(orderId);
    processPaymentEl.innerHTML = `
        <div class="process-card process-card--success">
            <div class="process-success-badge">Оплата подтверждена</div>
            <div id="order-lottie" class="process-lottie"></div>
            <h2 class="process-title">Оплата получена</h2>
            <p class="process-text process-text--lead">Оплата прошла успешно. Дальше мы обработаем заказ автоматически.</p>
            <div class="process-success-grid">
                <div class="process-success-note">
                    <div class="process-success-note__title">Оплата</div>
                    <div class="process-success-note__text">Платеж обработан через IntellectMoney.</div>
                </div>
                <div class="process-success-note">
                    <div class="process-success-note__title">Что дальше</div>
                    <div class="process-success-note__text">Мы продолжим обработку заказа без дополнительных действий с вашей стороны.</div>
                </div>
            </div>
            <div class="process-order-box process-order-box--success">
                <div class="process-order-label">Номер заказа</div>
                <div class="process-order-value">${escapeHtml(orderId || "—")}</div>
                ${paymentState?.invoice_id ? `<div class="process-hint">Счет: ${escapeHtml(paymentState.invoice_id)}</div>` : ""}
            </div>
        </div>
    `;
    showMainButton("В главное меню", exitProcessPaymentToHome);
    showBackButton(exitProcessPaymentToHome);
    const successKey = `sbp:${orderId}`;
    if (lastRenderedSuccessKey !== successKey) {
        lastRenderedSuccessKey = successKey;
        try {
            const lottieContainer = processPaymentEl.querySelector("#order-lottie");
            if (lottieContainer && typeof window !== "undefined" && window.lottie && !lottieContainer._lottieInited) {
                lottieContainer._lottieInited = true;
                window.lottie.loadAnimation({
                    container: lottieContainer,
                    renderer: "svg",
                    loop: false,
                    autoplay: true,
                    path: "/static/stickers/cherry-congrats.json",
                });
            }
        } catch (error) {
            console.warn("Lottie error:", error);
        }
        try {
            launchConfettiBurst?.();
        } catch (error) {
            console.warn("Confetti error:", error);
        }
    }
}


async function fetchAndRenderPaymentStatus(orderId, manualCheck = false) {
    if (!orderId) return;
    try {
        const result = await apiGet(`/payments/status?order_id=${encodeURIComponent(orderId)}`);
        sessionStorage.setItem("sbp_payment_state", JSON.stringify(result || {}));
        if ((result?.payment_status || "").toLowerCase() === "paid") {
            clearCheckoutState();
            renderSbpSuccess(orderId, result);
            return result;
        }
        if (["canceled", "error", "refunded"].includes((result?.payment_status || "").toLowerCase())) {
            renderSbpFailure(orderId, result);
            return result;
        }
        renderSbpPending(orderId, result);
        return result;
    } catch (error) {
        console.error("Failed to fetch payment status:", error);
        if (manualCheck) {
            alert(error?.message || "Не удалось проверить оплату.");
        }
        return null;
    }
}


function startPolling(orderId) {
    stopPaymentPolling();
    paymentPollTimer = window.setInterval(() => {
        void fetchAndRenderPaymentStatus(orderId, false);
    }, 5000);
}


export async function renderProcessPaymentPage() {
    stopPaymentPolling();
    const { orderId, result, mode } = getProcessParams();
    const paymentState = readJson("sbp_payment_state", {});

    if (mode === "later_success") {
        renderLaterSuccess(orderId);
        return;
    }

    if (!orderId && !paymentState?.order_number) {
        hideMainButton();
        hidePaymentFlowViews({ clearMarkup: true });
        navigateTo("/");
        return;
    }

    const effectiveOrderId = orderId || String(paymentState.order_number || "");
    if (result === "failed") {
        renderSbpFailure(effectiveOrderId, paymentState);
        return;
    }

    if (result === "success" || (paymentState?.payment_status || "").toLowerCase() === "paid") {
        await fetchAndRenderPaymentStatus(effectiveOrderId, false);
        return;
    }

    renderSbpPending(effectiveOrderId, paymentState);
    const resultState = await fetchAndRenderPaymentStatus(effectiveOrderId, false);
    const currentStatus = (resultState?.payment_status || "").toLowerCase();
    if (!["paid", "canceled", "error", "refunded"].includes(currentStatus)) {
        startPolling(effectiveOrderId);
    }
}
