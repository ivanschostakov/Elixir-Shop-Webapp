import { searchProducts } from "../../services/productService.js";
import { hideLoader, showLoader, withLoader } from "../ui/loader.js";
import { navigateTo } from "../router.js";
import { saveCart, state } from "../state.js";
import { hideBackButton, hideMainButton, showBackButton, showMainButton } from "../ui/telegram.js";
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
    tosOverlayEl,
} from "./constants.js";
import { apiGet, apiPost } from "../../services/api.js";

let page = 0;
let loading = false;
let mode = "home";

let tgCategoriesCache = null;
let selectedTgCategoryIds = new Set();
let filterUiBound = false;

function getSelectedCategoryIdsArray() {
    return Array.from(selectedTgCategoryIds).map(Number).filter(Number.isFinite);
}

async function fetchTgCategories() {
    const res = await apiGet("/tg-categories/");
    const items = Array.isArray(res) ? res : res?.data || res?.categories || [];
    return items
        .map((c) => ({
            id: Number(c.id),
            name: String(c.name ?? ""),
            description: c.description ?? null,
        }))
        .filter((c) => Number.isFinite(c.id) && c.name.trim().length > 0);
}

function ensureCategoryFilterOverlay() {
    let overlay = document.getElementById("tgcat-overlay");
    if (overlay) return overlay;

    overlay = document.createElement("div");
    overlay.id = "tgcat-overlay";
    overlay.style.cssText = `
    position: fixed;
    inset: 0;
    display: none;
    align-items: flex-end;
    justify-content: center;
    background: rgba(0,0,0,0.35);
    z-index: 9999;
    padding: 12px;
  `;

    overlay.innerHTML = `
    <div
      id="tgcat-modal"
      style="
        width: 100%;
        max-width: 520px;
        background: #fff;
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 12px 40px rgba(0,0,0,0.18);
        display: flex;
        flex-direction: column;
        max-height: 78vh;
      "
    >
      <div style="padding: 12px 14px; border-bottom: 1px solid #eef2f7; display:flex; align-items:center; justify-content:space-between; gap:10px;">
        <div style="font-weight:700; font-size: 15px; color:#111827;">Категории</div>
        <button id="tgcat-close" type="button" style="border:none; background:transparent; font-size:18px; line-height:1; cursor:pointer;">✕</button>
      </div>

      <div id="tgcat-list" style="padding: 10px 14px; overflow:auto;">
        <div style="color:#6b7280; font-size: 13px;">Загрузка…</div>
      </div>

      <div style="padding: 12px 14px; border-top: 1px solid #eef2f7; display:flex; gap:10px; justify-content:flex-end;">
        <button id="tgcat-reset" type="button" style="border:1px solid #e5e7eb; background:#fff; padding:10px 12px; border-radius: 12px; cursor:pointer; font-weight:600;">
          Сбросить
        </button>
      </div>
    </div>
  `;

    document.body.appendChild(overlay);
    return overlay;
}

function setFilterBtnBadge() {
    const btn = document.getElementById("filter-btn");
    if (!btn) return;
    const n = selectedTgCategoryIds.size;
    btn.textContent = n > 0 ? `Категории (${n})` : "Категории";
}

function renderCategoriesChecklist(categories) {
    const list = document.getElementById("tgcat-list");
    if (!list) return;

    if (!categories.length) {
        list.innerHTML = `<div style="color:#6b7280; font-size: 13px;">Категорий пока нет.</div>`;
        return;
    }

    list.innerHTML = categories
        .map((c) => {
            const checked = selectedTgCategoryIds.has(Number(c.id)) ? "checked" : "";
            const desc = c.description
                ? `<div style="color:#6b7280; font-size:12px; margin-top:2px;">${escapeHtml(
                    c.description
                )}</div>`
                : "";
            return `
        <label
          style="
            display:flex;
            gap:10px;
            padding:10px 8px;
            border:1px solid #eef2f7;
            border-radius:12px;
            margin-bottom:8px;
            cursor:pointer;
            align-items:flex-start;
          "
        >
          <input
            type="checkbox"
            class="tgcat-checkbox"
            data-id="${c.id}"
            ${checked}
            style="margin-top: 2px;"
          />
          <div style="min-width:0;">
            <div style="font-weight:700; font-size: 14px; color:#111827;">${escapeHtml(
                c.name
            )}</div>
            ${desc}
          </div>
        </label>
      `;
        })
        .join("");
}

async function openCategoryFilterOverlay() {
    const overlay = ensureCategoryFilterOverlay();
    overlay.style.display = "flex";
    document.body.style.overflow = "hidden";

    showMainButton("Применить", async () => {
        await applyCategoryFilterFromOverlay();
        hideMainButton();
    });

    try {
        if (!tgCategoriesCache) tgCategoriesCache = await fetchTgCategories();
        renderCategoriesChecklist(tgCategoriesCache);
    } catch (e) {
        console.error("[TG Categories] load failed:", e);
        const list = document.getElementById("tgcat-list");
        if (list) list.innerHTML = `<div style="color:#ef4444; font-size: 13px;">Не удалось загрузить категории</div>`;
    }
}

function closeCategoryFilterOverlay() {
    const overlay = document.getElementById("tgcat-overlay");
    if (!overlay) return;
    overlay.style.display = "none";
    document.body.style.overflow = "";
    hideMainButton();
}

async function applyCategoryFilterFromOverlay() {
    const checkboxes = Array.from(document.querySelectorAll(".tgcat-checkbox"));
    const next = new Set();
    for (const cb of checkboxes) {
        if (cb.checked) next.add(Number(cb.dataset.id));
    }
    selectedTgCategoryIds = next;
    setFilterBtnBadge();
    closeCategoryFilterOverlay();

    if (mode === "favourites") {
        await withLoader(openFavouritesPage);
    } else {
        page = 0;
        await withLoader(async () => {
            await loadMore(listEl, false, false);
        });
    }
}

let sortUiBound = false;
let sortBy = "name";
let sortDir = "asc";

function setSortBtnLabel() {
    const btn = document.getElementById("sort-btn");
    if (!btn) return;

    if (sortBy === "price") {
        btn.textContent = sortDir === "asc" ? "Сортировка: Цена ↑" : "Сортировка: Цена ↓";
    } else {
        btn.textContent = sortDir === "asc" ? "Сортировка: A→Z" : "Сортировка: Z→A";
    }
}

function ensureSortOverlay() {
    let overlay = document.getElementById("sort-overlay");
    if (overlay) return overlay;

    overlay = document.createElement("div");
    overlay.id = "sort-overlay";
    overlay.style.cssText = `
    position: fixed;
    inset: 0;
    display: none;
    align-items: flex-end;
    justify-content: center;
    background: rgba(0,0,0,0.35);
    z-index: 9999;
    padding: 12px;
  `;

    overlay.innerHTML = `
    <div
      id="sort-modal"
      style="
        width: 100%;
        max-width: 520px;
        background: #fff;
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 12px 40px rgba(0,0,0,0.18);
        display: flex;
        flex-direction: column;
        max-height: 70vh;
      "
    >
      <div style="padding: 12px 14px; border-bottom: 1px solid #eef2f7; display:flex; align-items:center; justify-content:space-between; gap:10px;">
        <div style="font-weight:700; font-size: 15px; color:#111827;">Сортировка</div>
        <button id="sort-close" type="button" style="border:none; background:transparent; font-size:18px; line-height:1; cursor:pointer;">✕</button>
      </div>

      <div style="padding: 10px 14px; overflow:auto;" id="sort-list"></div>
    </div>
  `;

    document.body.appendChild(overlay);
    return overlay;
}

function renderSortOptions() {
    const list = document.getElementById("sort-list");
    if (!list) return;

    const options = [
        { id: "name_asc", label: "По алфавиту A→Z", by: "name", dir: "asc" },
        { id: "name_desc", label: "По алфавиту Z→A", by: "name", dir: "desc" },
        { id: "price_asc", label: "По цене (дешевле → дороже)", by: "price", dir: "asc" },
        { id: "price_desc", label: "По цене (дороже → дешевле)", by: "price", dir: "desc" },
    ];

    list.innerHTML = options
        .map((o) => {
            const checked = sortBy === o.by && sortDir === o.dir ? "checked" : "";
            return `
        <label style="display:flex; gap:10px; padding:10px 8px; border:1px solid #eef2f7; border-radius:12px; margin-bottom:8px; cursor:pointer;">
          <input type="radio" name="sortmode" value="${o.id}" ${checked} />
          <div style="font-weight:700; font-size:14px; color:#111827;">${o.label}</div>
        </label>
      `;
        })
        .join("");
}

async function openSortOverlay() {
    const overlay = ensureSortOverlay();
    renderSortOptions();
    overlay.style.display = "flex";
    document.body.style.overflow = "hidden";

    showMainButton("Применить", async () => {
        await applySortFromOverlay();
        hideMainButton();
    });
}

function closeSortOverlay() {
    const overlay = document.getElementById("sort-overlay");
    if (!overlay) return;
    overlay.style.display = "none";
    document.body.style.overflow = "";
    hideMainButton();
}

async function applySortFromOverlay() {
    const picked = document.querySelector('input[name="sortmode"]:checked')?.value;
    if (picked === "price_asc") {
        sortBy = "price";
        sortDir = "asc";
    } else if (picked === "price_desc") {
        sortBy = "price";
        sortDir = "desc";
    } else if (picked === "name_desc") {
        sortBy = "name";
        sortDir = "desc";
    } else {
        sortBy = "name";
        sortDir = "asc";
    }

    setSortBtnLabel();
    closeSortOverlay();

    if (mode === "favourites") {
        await withLoader(openFavouritesPage);
    } else {
        page = 0;
        await withLoader(async () => {
            await loadMore(listEl, false, false);
        });
    }
}

function bindCategoryFilterUIOnce() {
    if (filterUiBound) return;

    const filterBtn = document.getElementById("filter-btn");
    if (filterBtn) {
        filterBtn.addEventListener("click", async () => {
            await openCategoryFilterOverlay();
        });
    }

    document.addEventListener(
        "click",
        (e) => {
            const overlay = document.getElementById("tgcat-overlay");
            if (!overlay || overlay.style.display === "none") return;

            const t = e.target;

            if (t === overlay) {
                closeCategoryFilterOverlay();
                return;
            }
            if (t && t.id === "tgcat-close") {
                closeCategoryFilterOverlay();
                return;
            }
            if (t && t.id === "tgcat-reset") {
                selectedTgCategoryIds.clear();
                if (tgCategoriesCache) renderCategoriesChecklist(tgCategoriesCache);
                setFilterBtnBadge();
                return;
            }
        },
        { passive: true }
    );

    filterUiBound = true;
}

function bindSortUIOnce() {
    if (sortUiBound) return;

    const sortBtn = document.getElementById("sort-btn");
    if (sortBtn) {
        sortBtn.addEventListener("click", async () => {
            await openSortOverlay();
        });
    }

    document.addEventListener(
        "click",
        (e) => {
            const overlay = document.getElementById("sort-overlay");
            if (!overlay || overlay.style.display === "none") return;

            const t = e.target;

            if (t === overlay) {
                closeSortOverlay();
                return;
            }
            if (t && t.id === "sort-close") {
                closeSortOverlay();
                return;
            }
        },
        { passive: true }
    );

    sortUiBound = true;
}

function updateCardImage(selectElement) {
    const card = selectElement.closest(".product-card");
    const img = card?.querySelector(".product-img");
    const selectedOption = selectElement.selectedOptions[0];

    if (!img || !selectedOption) return;

    const featureImgSrc = selectedOption.dataset.featureImg;
    const productImgSrc = img.dataset.productImg;
    const defaultImgSrc = "/static/images/product.png";

    img.onerror = () => {
        img.onerror = () => {
            img.onerror = null;
            img.src = defaultImgSrc;
        };
        img.src = productImgSrc;
    };
    img.src = featureImgSrc;
}

function productCardHTML(p) {
    const onecId = p.onec_id || (p.url ? p.url.split("/product/")[1] : "0");
    const rawFeatures = Array.isArray(p.features) ? p.features : [];

    const features = rawFeatures.map((f) => ({
        id: f.id,
        name: String(f.name ?? ""),
        price: Number(f.price ?? 0),
        balance: Number(f.balance ?? 0),
    }));

    const totalBalance = features.reduce((acc, f) => acc + (Number.isFinite(f.balance) ? f.balance : 0), 0);

    const sortedFeatures = features.slice().sort((a, b) => {
        const aOos = a.balance <= 0 ? 1 : 0;
        const bOos = b.balance <= 0 ? 1 : 0;
        if (aOos !== bOos) return aOos - bOos;
        return (b.price || 0) - (a.price || 0);
    });

    const productImgPath = `/static/images/${onecId}.png`;
    const defaultImgPath = "/static/images/product.png";

    const firstInStockId = sortedFeatures.find((f) => f.balance > 0)?.id ?? null;

    const featureSelector = sortedFeatures.length
        ? `
      <select class="feature-select" data-onec-id="${onecId}">
        ${sortedFeatures
            .map((f) => {
                const isOos = Number(f.balance ?? 0) <= 0;
                const disabled = isOos ? "disabled" : "";
                const selected = firstInStockId && f.id === firstInStockId ? "selected" : "";
                const label = isOos
                    ? `${escapeHtml(f.name)} - ${Number(f.price ?? 0)} ₽ (нет на складе)`
                    : `${escapeHtml(f.name)} - ${Number(f.price ?? 0)} ₽`;

                return `
            <option value="${escapeHtml(f.id)}"
                    ${disabled}
                    ${selected}
                    data-price="${Number(f.price ?? 0)}"
                    data-balance="${Number(f.balance ?? 0)}"
                    data-feature-img="/static/images/${escapeHtml(f.id)}.png">
              ${label}
            </option>
          `;
            })
            .join("")}
      </select>
    `
        : `
      <select class="feature-select" data-onec-id="${onecId}" disabled>
        <option value="" selected>Нет вариантов</option>
      </select>
    `;

    const buyArea =
        totalBalance > 0
            ? `<button class="buy-btn" data-onec-id="${onecId}"></button>`
            : `<button class="buy-btn buy-btn-oos" data-onec-id="${onecId}" data-disabled="1" disabled
                 style="opacity:.6; cursor:not-allowed; pointer-events:none;">
                 Нет на складе
               </button>`;

    return `
    <div class="product-card">
      <a href="/product/${onecId}" class="product-link" data-onec-id="${onecId}">
        <div class="product-image">
          <img src="${productImgPath}"
               data-product-img="${productImgPath}"
               data-default-img="${defaultImgPath}"
               alt="${escapeHtml(p.name)}"
               class="product-img"
               onerror="this.onerror=null; this.src='${defaultImgPath}';">
        </div>
      </a>

      <div class="product-info">
        <span class="product-name">${escapeHtml(p.name)}</span>
        ${featureSelector}
      </div>

      ${buyArea}
    </div>
  `;
}

function renderBuyCounter(btn, onecId) {
    const card = btn.closest(".product-card");
    const selector = card?.querySelector(".feature-select");
    const selectedFeatureId = selector?.value || null;
    const key = selectedFeatureId ? `${onecId}_${selectedFeatureId}` : onecId;

    const getMaxBalance = () => {
        if (!selector) return 0;
        const opt = selector.selectedOptions?.[0];
        if (!opt) return 0;
        const bal = Number(opt.dataset.balance ?? 0);
        if (!Number.isFinite(bal) || bal <= 0) return 0;
        return bal;
    };

    const maxBalance = getMaxBalance();

    const current = state.cart[key] || 0;
    const safeCount = Math.min(current, maxBalance);
    if (safeCount !== current) {
        if (safeCount > 0) state.cart[key] = safeCount;
        else delete state.cart[key];
    }
    const count = state.cart[key] || 0;

    btn.innerHTML = "";

    if (count === 0) {
        const add = document.createElement("button");
        add.textContent = "+ В корзину";
        add.className = "buy-btn-initial";
        add.onclick = () => {
            const max = getMaxBalance();
            if (max <= 0) return;
            state.cart[key] = 1;
            saveCart();
            renderBuyCounter(btn, onecId);
        };
        btn.appendChild(add);
    } else {
        const minus = document.createElement("button");
        minus.textContent = "−";
        minus.onclick = () => {
            const cur = state.cart[key] || 0;
            const next = cur - 1;
            if (next <= 0) delete state.cart[key];
            else state.cart[key] = next;
            saveCart();
            renderBuyCounter(btn, onecId);
        };

        const qty = document.createElement("span");
        qty.textContent = state.cart[key];
        qty.style.margin = "0 4px";

        const plus = document.createElement("button");
        plus.textContent = "+";
        plus.onclick = () => {
            const max = getMaxBalance();
            const cur = state.cart[key] || 0;
            if (max <= 0) return;
            if (cur >= max) return;
            state.cart[key] = cur + 1;
            saveCart();
            renderBuyCounter(btn, onecId);
        };

        btn.append(minus, qty, plus);
    }

    if (selector && !selector.dataset.counterBound) {
        selector.addEventListener("change", () => {
            renderBuyCounter(btn, onecId);
        });
        selector.dataset.counterBound = "1";
    }
}

function attachProductInteractions(container) {
    container.querySelectorAll(".product-link").forEach((link) => {
        link.addEventListener("click", (e) => {
            e.preventDefault();
            const id = link.dataset.onecId;
            navigateTo(`/product/${id}`);
        });
    });

    container.querySelectorAll(".feature-select").forEach((select) => {
        if (select.dataset.imageBound) return;

        const opt = select.selectedOptions?.[0];
        if (opt?.disabled) {
            const firstEnabled = Array.from(select.options).find((o) => !o.disabled);
            if (firstEnabled) {
                select.value = firstEnabled.value;
            }
        }

        updateCardImage(select);
        select.addEventListener("change", () => updateCardImage(select));
        select.dataset.imageBound = "1";
    });

    container.querySelectorAll(".buy-btn").forEach((btn) => {
        if (btn.dataset.initialized) return;

        if (btn.dataset.disabled === "1") {
            btn.dataset.initialized = "1";
            return;
        }

        renderBuyCounter(btn, btn.dataset.onecId);
        btn.dataset.initialized = "1";
    });
}

async function loadMore(container, append = false, useLoader = true) {
    if (loading) return;
    loading = true;

    try {
        const fetchFn = async () => {
            const collected = [];
            let localPage = page;

            const tg_category_ids = getSelectedCategoryIdsArray();

            while (true) {
                const data = await searchProducts({
                    q: "",
                    page: localPage,
                    tgCategoryIds: tg_category_ids,
                    tgCategoryMode: "all",
                    sortBy,
                    sortDir,
                });

                const rawResults = Array.isArray(data.results) ? data.results : [];
                if (!rawResults.length) break;

                for (const p of rawResults) {
                    collected.push(p);
                    if (collected.length >= 6) break;
                }

                localPage += 1;
                if (collected.length >= 6) break;
            }

            page = localPage;
            return collected;
        };

        const results = useLoader ? await withLoader(fetchFn) : await fetchFn();
        const html = results.map(productCardHTML).join("");

        if (append) container.insertAdjacentHTML("beforeend", html);
        else container.innerHTML = html;

        attachProductInteractions(container);
    } catch (err) {
        console.error("[Products] load failed:", err);
    } finally {
        loading = false;
    }
}

function setupInfiniteScroll(container) {
    function onScroll() {
        if (mode !== "home") return;
        if (container.style.display === "none") return;

        const st = document.documentElement.scrollTop || document.body.scrollTop;
        const sh = document.documentElement.scrollHeight || document.body.scrollHeight;
        const ch = document.documentElement.clientHeight;
        if (st + ch >= sh - 200) loadMore(container, true);
    }
    window.addEventListener("scroll", onScroll);
}

async function getUser() {
    const initData = state.telegram.initData || "";
    const payload = { initData };
    const result = await apiPost("/auth", payload);
    state.user = result.user;
    return result.user;
}

async function openHomePage() {
    mode = "home";
    hideMainButton();
    hideBackButton();

    navBottomEl.style.display = "flex";
    headerTitle.textContent = "Магазин ElixirPeptide";
    tosOverlayEl.style.display = "none";
    listEl.style.display = "grid";
    toolbarEl.style.display = "flex";
    searchBtnEl.style.display = "flex";
    detailEl.style.display = "none";
    cartPageEl.style.display = "none";
    checkoutPageEl.style.display = "none";
    contactPageEl.style.display = "none";
    paymentPageEl.style.display = "none";
    processPaymentEl.style.display = "none";
    profilePageEl.style.display = "none";
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "none";

    bindCategoryFilterUIOnce();
    bindSortUIOnce();
    setFilterBtnBadge();
    setSortBtnLabel();

    page = 0;
    await loadMore(listEl, false);
    setupInfiniteScroll(listEl);
}

async function openFavouritesPage() {
    mode = "favourites";
    hideMainButton();
    showBackButton();

    navBottomEl.style.display = "flex";
    headerTitle.textContent = "Избранное";
    tosOverlayEl.style.display = "none";
    listEl.style.display = "grid";
    toolbarEl.style.display = "flex";
    searchBtnEl.style.display = "none";
    detailEl.style.display = "none";
    cartPageEl.style.display = "none";
    checkoutPageEl.style.display = "none";
    contactPageEl.style.display = "none";
    paymentPageEl.style.display = "none";
    processPaymentEl.style.display = "none";
    profilePageEl.style.display = "none";
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "none";

    bindCategoryFilterUIOnce();
    bindSortUIOnce();
    setFilterBtnBadge();
    setSortBtnLabel();

    const favIds = state?.user?.favourites || [];
    if (!favIds.length) {
        listEl.innerHTML = `
      <div style="grid-column:1 / -1; text-align:center; padding:24px 12px;">
        <h2 style="margin-bottom:8px; font-size:18px;">У вас пока нет избранных товаров</h2>
        <p style="margin:0; font-size:14px; color:#6b7280;">
          Нажимайте на сердечко на странице товара, чтобы добавить его в избранное.
        </p>
        <div id="empty-fav-lottie" style="margin-top:16px; max-width:220px; width:100%; height:220px; display:block; margin-left:auto; margin-right:auto; border-radius:12px; overflow:hidden;"></div>
      </div>
    `;

        const animContainer = document.getElementById("empty-fav-lottie");
        if (animContainer && window.lottie) {
            window.lottie.loadAnimation({
                container: animContainer,
                renderer: "svg",
                loop: true,
                autoplay: true,
                path: "/static/stickers/utya-fav.json",
                rendererSettings: { preserveAspectRatio: "xMidYMid meet" },
            });
        }
        return;
    }

    const favSet = new Set(favIds.map(String));
    const tg_category_ids = getSelectedCategoryIdsArray();

    const fetchFn = async () => {
        const data = await searchProducts({
            q: "",
            page: 0,
            limit: 500,
            tgCategoryIds: tg_category_ids,
            tgCategoryMode: "all",
            sortBy,
            sortDir,
        });

        const all = Array.isArray(data?.results) ? data.results : [];
        return all.filter((p) => {
            const onecId = p.onec_id || (p.url ? p.url.split("/product/")[1] : "0");
            return favSet.has(String(onecId));
        });
    };

    try {
        const results = await withLoader(fetchFn);
        if (!results.length) {
            listEl.innerHTML = `
        <div style="grid-column:1 / -1; text-align:center; padding:24px 12px;">
          <h2 style="margin-bottom:8px; font-size:18px;">Не удалось загрузить избранные</h2>
          <p style="margin:0; font-size:14px; color:#6b7280;">Попробуйте позже.</p>
        </div>
      `;
            return;
        }

        listEl.innerHTML = results.map(productCardHTML).join("");
        attachProductInteractions(listEl);
    } catch (err) {
        console.error("[Favourites] load failed:", err);
        listEl.innerHTML = `
      <div style="grid-column:1 / -1; text-align:center; padding:24px 12px;">
        <h2 style="margin-bottom:8px; font-size:18px;">Ошибка загрузки избранных</h2>
        <p style="margin:0; font-size:14px; color:#6b7280;">Пожалуйста, попробуйте позже.</p>
      </div>
    `;
    }
}

function closeTosOverlay() {
    if (!tosOverlayEl) return;
    tosOverlayEl.classList.add("hidden");
    tosOverlayEl.style.display = "none";
    document.body.style.overflow = "";
    hideMainButton();
}

async function openTosOverlay(user) {
    if (!tosOverlayEl) return;

    const tosBodyEl = document.getElementById("tos-body");

    if (tosBodyEl && !tosBodyEl.dataset.loaded) {
        try {
            const res = await fetch("/static/offer.html", { cache: "no-cache" });
            if (!res.ok) throw new Error("Failed to load offer.html");
            tosBodyEl.innerHTML = await res.text();
            tosBodyEl.dataset.loaded = "1";
        } catch (err) {
            console.error("Не удалось загрузить offer.html:", err);
            tosBodyEl.innerHTML = "<p>Не удалось загрузить текст публичной оферты. Попробуйте позже.</p>";
        }
    }

    tosOverlayEl.classList.remove("hidden");
    tosOverlayEl.style.display = "flex";
    document.body.style.overflow = "hidden";

    let acceptMode = false;

    const setAcceptButton = () => {
        if (acceptMode) return;
        acceptMode = true;

        showMainButton("Прочитал(а) и соглашаюсь", async () => {
            const payload = {
                user_id: user.tg_id,
                phone: "123456789",
                email: "123456789@gmail.com",
                is_active: true,
                name: "Начальная",
                sum: "0.00",
                delivery_sum: "0.00",
                delivery_string: "Начальная",
                commentary: "Начальная",
            };
            await apiPost("/cart/create", payload);

            const currentUser = state.user || user;
            if (currentUser) {
                currentUser.accepted_terms = true;
                state.user = currentUser;
            }

            await withLoader(openHomePage);
            closeTosOverlay();
        });
    };

    if (tosBodyEl && !tosBodyEl.dataset.scrollBound) {
        tosBodyEl.addEventListener("scroll", () => {
            const atBottom =
                tosBodyEl.scrollTop + tosBodyEl.clientHeight >= tosBodyEl.scrollHeight - 10;
            if (!acceptMode && atBottom) setAcceptButton();
        });
        tosBodyEl.dataset.scrollBound = "1";
    }

    showMainButton("Прокрутить вниз", () => {
        const body = document.getElementById("tos-body");
        if (body) body.scrollTo({ top: body.scrollHeight, behavior: "smooth" });
        setAcceptButton();
    });
}

export async function renderHomePage() {
    showLoader();
    const user = state.user || (await getUser());
    if (!user) {
        await openHomePage();
    } else {
        document.getElementById("bottom-nav-avatar").src =
            user.photo_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=user${user.tg_id}`;
        state.user = user;
        if (!user.accepted_terms) openTosOverlay(user);
        else await openHomePage();
    }
    hideLoader();
}

export async function renderFavouritesPage() {
    const user = state.user || (await getUser());
    if (!user) {
        console.warn("[Favourites] invalid user (auth failed)");
    } else {
        document.getElementById("bottom-nav-avatar").src =
            user.photo_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=user${user.tg_id}`;
        state.user = user;
        if (!user.accepted_terms) openTosOverlay(user);
        else await openFavouritesPage();
    }
}

function escapeHtml(s) {
    return String(s ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
