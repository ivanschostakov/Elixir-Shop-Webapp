import {
    cartPageEl, checkoutPageEl, contactPageEl,
    detailEl,
    headerTitle,
    listEl,
    navBottomEl, orderDetailEl, ordersPageEl, paymentPageEl, processPaymentEl, profilePageEl,
    searchBtnEl,
    toolbarEl,
    tosOverlayEl
} from "./constants.js";

import { state } from "../state.js";
import { apiGet } from "../../services/api.js";

function getStatusText(cart) {
    const s = (cart.status ?? "").toString().trim();
    if (s) return s;
    return cart.is_active ? "В обработке" : "Обработан";
}

function getStatusBadgeClass(statusText) {
    const t = (statusText ?? "").toLowerCase().trim();

    if (t === "создан") return "order-card-status--created";
    if (t === "оплачен") return "order-card-status--paid";
    if (t === "укомплектован") return "order-card-status--packed";
    if (t === "отправлен") return "order-card-status--sent";
    if (t === "доставлен") return "order-card-status--delivered";
    if (t === "закрыт" || t === "обработан") return "order-card-status--closed";
    if (t === "не найден") return "order-card-status--notfound";
    if (t === "в обработке") return "order-card-status--inprogress";

    return "order-card-status--default";
}


function getPaymentMethodText(cart) {
    const paymentMethod = (cart.payment_method || "").toLowerCase().trim();
    const paymentStatus = (cart.payment_status || "").toLowerCase().trim();
    const methodText = paymentMethod === "sbp"
        ? "СБП через IntellectMoney"
        : paymentMethod === "later"
            ? "Оплата позже"
            : "—";
    if (!paymentStatus) return methodText;

    const statusText = paymentStatus === "paid"
        ? "оплачен"
        : paymentStatus === "pending"
            ? "ожидает оплаты"
            : paymentStatus === "created"
                ? "счет создан"
                : paymentStatus === "canceled"
                    ? "отменен"
                    : paymentStatus === "error"
                        ? "ошибка"
                        : paymentStatus === "refunded"
                            ? "возвращен"
                            : paymentStatus;
    return `${methodText} (${statusText})`;
}

export async function renderOrdersPage() {
    navBottomEl.style.display = "flex";
    headerTitle.textContent = "Мои заказы";
    tosOverlayEl.style.display = "none";
    listEl.style.display = "none";
    toolbarEl.style.display = "none";
    searchBtnEl.style.display = "none";
    detailEl.style.display = "none";
    cartPageEl.style.display = "none";
    checkoutPageEl.style.display = "none";
    contactPageEl.style.display = "none";
    paymentPageEl.style.display = "none";
    processPaymentEl.style.display = "none";
    profilePageEl.style.display = "none";
    ordersPageEl.style.display = "block";
    orderDetailEl.style.display = "none";

    initOrdersSectionToggles();
    await loadAndRenderOrders();
}

async function loadAndRenderOrders() {
    const user = state.user;
    if (!user?.tg_id) {
        renderOrdersLists([], []);
        return;
    }

    let result;
    try {
        result = await apiGet(`/cart/?user_id=${user.tg_id}`);
    } catch (e) {
        console.error("Failed to load carts:", e);
        renderOrdersLists([], []);
        return;
    }

    const carts = Array.isArray(result) ? result : (result?.data || result?.carts || []);
    const normalized = carts.map(normalizeCart);

    const active = normalized.filter((c) => c.is_active === true);
    const processed = normalized.filter((c) => c.is_active === false);

    active.sort((a, b) => b.created_ts - a.created_ts);
    processed.sort((a, b) => b.created_ts - a.created_ts);

    renderOrdersLists(active, processed);
}

function renderOrdersLists(active, processed) {
    const activeList = document.getElementById("orders-active-list");
    const processedList = document.getElementById("orders-processed-list");

    const activeCount = document.getElementById("orders-active-count");
    const processedCount = document.getElementById("orders-processed-count");

    const activeEmpty = document.getElementById("orders-active-empty");
    const processedEmpty = document.getElementById("orders-processed-empty");

    if (!activeList || !processedList) return;

    activeList.innerHTML = "";
    processedList.innerHTML = "";

    if (activeCount) activeCount.textContent = String(active.length);
    if (processedCount) processedCount.textContent = String(processed.length);

    if (active.length === 0) {
        if (activeEmpty) activeEmpty.style.display = "block";
    } else {
        if (activeEmpty) activeEmpty.style.display = "none";
        active.forEach((cart) => activeList.appendChild(renderOrderCard(cart)));
    }

    if (processed.length === 0) {
        if (processedEmpty) processedEmpty.style.display = "block";
    } else {
        if (processedEmpty) processedEmpty.style.display = "none";
        processed.forEach((cart) => processedList.appendChild(renderOrderCard(cart)));
    }

    autoCollapseIfEmpty();
}

function initOrdersSectionToggles() {
    const root = document.querySelector("#orders-page");
    if (!root) return;

    root.querySelectorAll(".orders-section").forEach((section) => {
        const header = section.querySelector(".orders-section-header");
        if (!header) return;

        if (header.dataset.toggleBound === "1") return;
        header.dataset.toggleBound = "1";

        header.setAttribute("role", "button");
        header.tabIndex = 0;

        if (!header.querySelector(".orders-section-chevron")) {
            const chev = document.createElement("span");
            chev.className = "orders-section-chevron";
            chev.textContent = "▾";
            header.appendChild(chev);
        }

        if (!section.querySelector(".orders-section-body")) {
            const body = document.createElement("div");
            body.className = "orders-section-body";

            const childrenToMove = [];
            section.childNodes.forEach((node) => {
                if (node.nodeType === 1 && node.classList.contains("orders-section-header")) return;
                if (node.nodeType === 3 && node.textContent.trim() === "") return;
                childrenToMove.push(node);
            });

            childrenToMove.forEach((n) => body.appendChild(n));
            section.appendChild(body);
        }

        const setCollapsed = (collapsed) => {
            section.classList.toggle("is-collapsed", collapsed);
            header.setAttribute("aria-expanded", String(!collapsed));
        };

        setCollapsed(false);

        header.addEventListener("click", () => {
            setCollapsed(!section.classList.contains("is-collapsed"));
        });

        header.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                header.click();
            }
        });
    });
}

function renderOrderCard(cart) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "order-card";

    const statusText = getStatusText(cart);
    const statusClass = getStatusBadgeClass(statusText);

    const dateText = cart.created_at ? formatDateTime(cart.created_at) : "—";
    const totalText = formatMoney(cart.sum);

    const deliveryText =
        cart.delivery_string && String(cart.delivery_string).trim()
            ? cart.delivery_string
            : "Доставка не указана";

    btn.innerHTML = `
    <div class="order-card-top">
      <div class="order-card-id-row">
        <div class="order-card-id">${escapeHtml(cart.name || `Заказ #${cart.id}`)}</div>
        <span class="order-card-status ${statusClass}">${escapeHtml(statusText)}</span>
      </div>

      <div class="order-card-meta">
        <span class="order-card-date">${escapeHtml(dateText)}</span>
        <span class="order-card-total">${escapeHtml(totalText)}</span>
      </div>
    </div>

    <div class="order-card-bottom">
      <div class="order-card-delivery">${escapeHtml(deliveryText)}</div>
      <div class="order-card-chevron">›</div>
    </div>
  `;

    btn.addEventListener("click", () => openOrderDetail(cart));
    return btn;
}

function openOrderDetail(cart) {
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "block";
    detailEl.style.display = "block";

    const idEl = document.getElementById("order-detail-id");
    const statusEl = document.getElementById("order-detail-status");
    const dateEl = document.getElementById("order-detail-date");

    if (idEl) idEl.textContent = String(cart.id);

    if (statusEl) {
        const statusText = getStatusText(cart);
        statusEl.textContent = statusText;
        statusEl.className = `order-detail-status ${getStatusBadgeClass(statusText)}`;
    }

    if (dateEl) dateEl.textContent = cart.created_at ? formatDateTime(cart.created_at) : "—";

    const deliverySummaryEl = document.getElementById("order-delivery-summary");
    if (deliverySummaryEl) {
        deliverySummaryEl.textContent =
            cart.delivery_string && String(cart.delivery_string).trim()
                ? cart.delivery_string
                : "Доставка не указана";
    }

    const paymentMethodEl = document.getElementById("order-payment-method");
    if (paymentMethodEl) paymentMethodEl.textContent = getPaymentMethodText(cart);

    const commentEl = document.getElementById("order-comment-text");
    if (commentEl) commentEl.textContent = cart.commentary ? String(cart.commentary) : "—";

    const subtotalEl = document.getElementById("order-subtotal");
    const deliveryPriceEl = document.getElementById("order-delivery-price");
    const totalEl = document.getElementById("order-total");

    if (subtotalEl) subtotalEl.textContent = formatMoney(cart.sum);
    if (deliveryPriceEl) deliveryPriceEl.textContent = formatMoney(cart.delivery_sum);

    const totalNum = toNumber(cart.sum) + toNumber(cart.delivery_sum);
    if (totalEl) totalEl.textContent = formatMoney(totalNum);

    const phoneEl = document.getElementById("order-contact-phone");
    const emailEl = document.getElementById("order-contact-email");
    if (phoneEl) phoneEl.textContent = (cart.phone || "").toString().trim() || "Не указан";
    if (emailEl) emailEl.textContent = (cart.email || "").toString().trim() || "Не указан";

    const itemsListEl = document.getElementById("order-items-list");
    if (itemsListEl) {
        itemsListEl.innerHTML = "";

        const items = Array.isArray(cart.items) ? cart.items : [];
        if (items.length === 0) {
            const empty = document.createElement("div");
            empty.className = "order-detail-text";
            empty.textContent = "— нет товаров —";
            itemsListEl.appendChild(empty);
        } else {
            items.forEach((it) => itemsListEl.appendChild(renderOrderItemRow(it)));
        }
    }
}

function renderOrderItemRow(it) {

    const name = it.product?.name ?? "Товар";
    const variant = it.feature?.name ?? "";
    const qty = Number(it.quantity) || 1;
    const price = toNumber(it.feature?.price);
    const line = price * qty;

    const row = document.createElement("div");
    row.className = "order-item-row";

    const title = variant ? `${name} (${variant})` : name;

    row.innerHTML = `
    <div class="order-item-row__top">
      <div class="order-item-row__name">${escapeHtml(title)}</div>
      <div class="order-item-row__sum">${escapeHtml(formatMoney(line))}</div>
    </div>

    <div class="order-item-row__bottom">
      <div class="order-item-row__meta">
        ${escapeHtml(qty)} × ${escapeHtml(formatMoney(price))}
      </div>
    </div>
  `;

    return row;
}

function normalizeCart(raw) {

    const created = raw.created_at;
    const updated = raw.updated_at;

    return {
        id: raw.id,
        name: raw.name,
        user_id: raw.user_id,

        status: raw.status,

        sum: toNumber(raw.sum),
        delivery_sum: toNumber(raw.delivery_sum),
        delivery_string: raw.delivery_string,
        commentary: raw.commentary,
        payment_method: raw.payment_method,
        payment_status: raw.payment_status,

        phone: raw.phone,
        email: raw.email,

        is_active: Boolean(raw.is_active),

        created_at: created,
        updated_at: updated,
        created_ts: created ? Date.parse(created) : 0,

        items: Array.isArray(raw.items) ? raw.items : [],
    };
}

function autoCollapseIfEmpty() {
    const activeSection = document.querySelector("#orders-page .orders-section:nth-of-type(1)");
    const processedSection = document.querySelector("#orders-page .orders-section:nth-of-type(2)");

    const activeCount = document.getElementById("orders-active-count");
    const processedCount = document.getElementById("orders-processed-count");

    if (activeSection && activeCount && Number(activeCount.textContent) === 0) {
        activeSection.classList.add("is-collapsed");
    }
    if (processedSection && processedCount && Number(processedCount.textContent) === 0) {
        processedSection.classList.add("is-collapsed");
    }
}

function toNumber(v) {
    if (v == null) return 0;
    const n = Number(String(v).replace(",", "."));
    return Number.isFinite(n) ? n : 0;
}

function formatMoney(v) {
    const n = toNumber(v);
    const rounded = Math.round(n * 100) / 100;
    const parts = rounded.toFixed(2).split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return `${parts.join(".")} ₽`;
}

function formatDateTime(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);

    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const yy = String(d.getFullYear());
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");

    return `${dd}.${mm}.${yy} ${hh}:${mi}`;
}

function escapeHtml(s) {
    return String(s ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
