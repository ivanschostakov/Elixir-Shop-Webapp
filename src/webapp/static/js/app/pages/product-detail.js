import { getProductDetail } from "../../services/productService.js";
import { withLoader } from "../ui/loader.js";
import { state, saveCart } from "../state.js";
import {
    showBackButton,
    showMainButton,
    updateMainButton,
    hideMainButton,
    hideBackButton,
    isTelegramApp,
    openTgLink,
} from "../ui/telegram.js";
import { navigateTo } from "../router.js";
import {
    cartPageEl,
    checkoutPageEl,
    contactPageEl,
    detailEl,
    headerTitle,
    listEl,
    navBottomEl, orderDetailEl, ordersPageEl,
    paymentPageEl,
    processPaymentEl, profilePageEl,
    searchBtnEl,
    toolbarEl
} from "./constants.js";
import {
    setSearchButtonToFavorite,
    setFavoriteButtonActive,
    restoreSearchButtonToSearch
} from "./search.js";
import { apiDelete, apiPost } from "../../services/api.js";

function isProductFavorite(onec_id) {
    const favs = state?.user?.favourites || [];
    return favs.some((id) => String(id) === String(onec_id));
}

function updateLocalFavourites(onec_id, shouldBeFav) {
    const favs = state.user.favourites || [];
    if (shouldBeFav) {
        if (!favs.some((id) => String(id) === String(onec_id))) {
            state.user.favourites = [...favs, onec_id];
        }
    } else {
        state.user.favourites = favs.filter((id) => String(id) !== String(onec_id));
    }
}

export async function renderProductDetailPage(onec_id) {
    const productImgPath = `/static/images/${onec_id}.png`;
    const defaultImgPath = "/static/images/product.png";

    navBottomEl.style.display = "none";
    toolbarEl.style.display = "none";
    listEl.style.display = "none";
    contactPageEl.style.display = "none";
    cartPageEl.style.display = "none";
    checkoutPageEl.style.display = "none";
    paymentPageEl.style.display = "none";
    profilePageEl.style.display = "none";
    headerTitle.textContent = "Информация о продукте";
    searchBtnEl.style.display = "flex";
    detailEl.style.display = "block";
    processPaymentEl.style.display = "none";
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "none";

    const initiallyFav = isProductFavorite(onec_id);

    const onFavoriteClick = async (currentlyActive) => {

        const nextState = !currentlyActive;

        setFavoriteButtonActive(nextState);

        updateLocalFavourites(onec_id, nextState);

        const payload = { user_id: state.user.tg_id, onec_id };

        try {
            if (nextState) {
                await apiPost("/favourites", payload);
            } else {
                await apiDelete("/favourites", payload);
            }

        } catch (err) {
            console.error("Failed to toggle favourite:", err);

            setFavoriteButtonActive(!nextState);
            updateLocalFavourites(onec_id, !nextState);

        }
    };

    setSearchButtonToFavorite(onFavoriteClick, initiallyFav);

    const cleanupProductPage = () => {

        restoreSearchButtonToSearch();

        if (isTelegramApp()) {
            hideMainButton();
        }
    };
    const data = await withLoader(() => getProductDetail(onec_id));

    if (data?.error) {
        detailEl.innerHTML = `
      <div class="error-message" style="padding:20px;text-align:center">
        <h2>Ошибка загрузки</h2>
        <p>Не удалось загрузить информацию о товаре.</p>
      </div>`;
        if (isTelegramApp()) {
            hideMainButton();
            const offBack = showBackButton(() => {
                cleanupProductPage();
                navigateTo('/');
            });
            window.addEventListener("popstate", () => {
                offBack?.();
                cleanupProductPage();
            }, { once: true });
        }
        return;
    }

    const features = data.features || [];
    const totalBalance = features.reduce((sum, f) => sum + Math.max(0, Number(f.balance ?? 0) || 0), 0);
    const productInStock = totalBalance > 0;

    const featuresTableHtml = `
    <div class="product-features">
      <h2>Вариации</h2>
      <table class="features-table">
        <thead>
          <tr>
            <th data-key="name">Вид</th>
            <th data-key="price">Цена</th>
            <th data-key="balance">Склад</th>
            <th>Кол-во</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>`;

    detailEl.innerHTML = `
    <div class="product-detail-container">
      <div class="product-main">
        <div class="product-image">
          <img
            src="${productImgPath}"
            alt="${data.product.name || ""}"
            onerror="this.onerror=null;this.src='${defaultImgPath}';"
          >
          <div class="product-media-actions">
            <button class="product-media-action product-share-btn" type="button" aria-label="Поделиться">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="18" cy="5" r="3"></circle>
                <circle cx="6" cy="12" r="3"></circle>
                <circle cx="18" cy="19" r="3"></circle>
                <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line>
                <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>
              </svg>
            </button>
          </div>
        </div>
        <div class="product-info">
          <h1></h1>
          <div class="product-description"></div>
          <div class="product-meta">
            ${data.product.usage ? `<p><strong>Применение:</strong> <span class="product-usage"></span></p>` : ""}
            ${data.product.expiration ? `<p><strong>Срок годности:</strong> <span class="product-expiration"></span></p>` : ""}
          </div>
        </div>
      </div>
    </div>`;

    const infoEl = detailEl.querySelector(".product-info");
    infoEl.querySelector("h1").textContent = data.product.name;
    infoEl.querySelector(".product-description").innerHTML = data.product.description || "Нет описания";
    if (data.product.usage) infoEl.querySelector(".product-usage").innerHTML = data.product.usage;
    if (data.product.expiration) infoEl.querySelector(".product-expiration").innerHTML = data.product.expiration;
    detailEl.querySelector(".product-image img").alt = data.product.name;
    setupShareButton(detailEl, data, onec_id);

    const descEl = infoEl.querySelector(".product-description");
    setupDescriptionClamp(descEl);

    const sheet = createBottomSheet(featuresTableHtml);
    document.body.appendChild(sheet.root);

    const tbody = sheet.root.querySelector(".features-table tbody");
    const headers = sheet.root.querySelectorAll(".features-table th[data-key]");
    let sortKey = "price";
    let sortAsc = true;

    const getCartKey = (f) => `${onec_id}_${f.id ?? f.onec_id ?? f.name}`;
    const getQty = (key) => Number(state.cart?.[key] || 0);
    const setQty = (key, qty) => {
        if (!state.cart) state.cart = {};
        if (qty <= 0) delete state.cart[key];
        else state.cart[key] = qty;
        saveCart();
    };

    const sortVal = (item, key) => {
        if (key === "price" || key === "balance") return Number(item[key]) || 0;
        const v = item[key];
        return typeof v === "string" ? v.toLowerCase() : v ?? "";
    };

    const renderTableBody = () => {
        const sorted = [...features].sort((a, b) => {
            const av = sortVal(a, sortKey);
            const bv = sortVal(b, sortKey);
            if (typeof av === "string" && typeof bv === "string") {
                return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
            }
            return sortAsc ? av - bv : bv - av;
        });

        tbody.innerHTML = "";
        for (const f of sorted) {
            const key = getCartKey(f);
            const tr = document.createElement("tr");

            const balNum = Number(f.balance) || 0;
            const isOOS = balNum <= 0;

            tr.dataset.key = key;
            tr.dataset.balance = String(balNum);
            if (isOOS) tr.classList.add("oos-row");

            const tdName = document.createElement("td");
            tdName.textContent = f.name;

            const tdPrice = document.createElement("td");
            tdPrice.textContent = `${Number(f.price).toLocaleString("ru-RU")} ₽`;

            const tdBal = document.createElement("td");

            let stockLabel = "";
            let stockClass = "";

            if (balNum <= 0) {
                stockLabel = "Нет на складе";
                stockClass = "stock-badge stock-badge--oos";
            } else if (balNum < 10) {
                stockLabel = "Мало";
                stockClass = "stock-badge stock-badge--low";
            } else {
                stockLabel = "Много";
                stockClass = "stock-badge stock-badge--ok";
            }

            tdBal.innerHTML = `<span class="${stockClass}">${stockLabel}</span>`;

            const tdQty = document.createElement("td");
            if (isOOS) {
                tdQty.innerHTML = ``;
            } else {
                tdQty.innerHTML = `
          <div class="cart-qty-ctrl">
            <button class="qty-dec" aria-label="Уменьшить количество">−</button>
            <span class="qty-val">${getQty(key)}</span>
            <button class="qty-inc" aria-label="Увеличить количество">+</button>
          </div>`;
            }

            tr.append(tdName, tdPrice, tdBal, tdQty);
            tbody.appendChild(tr);
        }

        headers.forEach((h) => {
            let label =
                h.dataset.key === "name"
                    ? "Вид"
                    : h.dataset.key === "price"
                        ? "Цена"
                        : "Склад";
            if (h.dataset.key === sortKey) label += sortAsc ? " ▲" : " ▼";
            h.textContent = label;
        });
    };

    headers.forEach((h) => {
        h.style.cursor = "pointer";
        h.addEventListener("click", () => {
            const key = h.dataset.key;
            sortAsc = sortKey === key ? !sortAsc : true;
            sortKey = key;
            renderTableBody();
        });
    });

    tbody.addEventListener("click", (e) => {
        const dec = e.target.closest(".qty-dec");
        const inc = e.target.closest(".qty-inc");
        if (!dec && !inc) return;

        const tr = e.target.closest("tr");
        const balance = Number(tr.dataset.balance || 0);
        if (balance <= 0) return;

        const key = tr.dataset.key;
        const span = tr.querySelector(".qty-val");

        let qty = getQty(key);
        if (dec) qty = Math.max(0, qty - 1);
        if (inc) qty = Math.min(balance, qty + 1);

        setQty(key, qty);
        span.textContent = qty;
    });

    renderTableBody();

    if (isTelegramApp()) {
        let offBack;

        const setBackForProduct = () => {
            if (offBack) offBack();
            offBack = showBackButton(() => {
                if (sheet.isOpen()) {
                    sheet.close(true);
                } else {
                    cleanupProductPage();
                    navigateTo("/");
                }
            });
        };

        setBackForProduct();

        if (!productInStock) {

            showMainButton("Нет на складе", () => {});

            window.addEventListener(
                "popstate",
                () => {
                    offBack?.();
                    sheet.close(true);
                    cleanupProductPage();
                },
                { once: true }
            );
        } else {

            const toggleSheet = () => {
                if (sheet.isOpen()) {
                    sheet.close(false);
                } else {
                    sheet.open();
                    hideBackButton();
                    updateMainButton("Скрыть варианты");
                }
            };

            showMainButton("Выбрать дозировку", toggleSheet);

            sheet.onClose(() => {
                updateMainButton("Выбрать дозировку");
                setBackForProduct();
            });

            window.addEventListener(
                "popstate",
                () => {
                    offBack?.();
                    sheet.close(true);
                    cleanupProductPage();
                },
                { once: true }
            );
        }
    } else {

        const openSheetBtn = document.createElement("button");
        openSheetBtn.className = "buy-btn";

        if (!productInStock) {
            openSheetBtn.textContent = "Нет на складе";
            openSheetBtn.disabled = true;
            openSheetBtn.style.opacity = "0.6";
            openSheetBtn.style.cursor = "not-allowed";
            openSheetBtn.style.pointerEvents = "none";
        } else {
            openSheetBtn.textContent = "Выбрать дозировку";
            openSheetBtn.onclick = () => sheet.open();
        }

        detailEl.querySelector(".product-detail-container").appendChild(openSheetBtn);
    }
}

function createBottomSheet(innerHTML) {
    const root = document.createElement("div");
    root.className = "sheet-root";
    root.innerHTML = `
    <div class="sheet-backdrop"></div>
    <div class="sheet-panel" role="dialog" aria-modal="true" aria-label="Вариации">
      <div class="sheet-handle"></div>
      <div class="sheet-content">${innerHTML}</div>
    </div>`;

    const backdrop = root.querySelector(".sheet-backdrop");
    const panel = root.querySelector(".sheet-panel");

    const OPEN_CLASS = "open";
    const CLOSE_THRESHOLD_PX = 140;
    let opened = false;
    let dragging = false;
    let startY = 0;
    let currentY = 0;
    const closeCallbacks = new Set();

    const markClosed = () => {
        opened = false;
        closeCallbacks.forEach((fn) => {
            try { fn(); } catch {}
        });
    };

    const open = () => {
        root.classList.add(OPEN_CLASS);
        opened = true;
    };

    const close = (instant = false) => {
        if (!root.classList.contains(OPEN_CLASS)) return;
        const finish = () => {
            panel.style.transition = "";
            panel.style.transform = "";
            root.classList.remove(OPEN_CLASS);
            markClosed();
        };
        if (instant) return finish();
        panel.style.transition =
            "transform var(--dur-base,220ms) var(--easing,cubic-bezier(.2,.8,.2,1))";
        panel.style.transform = "translate(-50%, 100%)";
        setTimeout(finish, 220);
    };

    const startDrag = (y) => {
        dragging = true;
        startY = y;
        currentY = y;
        panel.style.transition = "none";
    };
    const moveDrag = (y) => {
        if (!dragging) return;
        currentY = y;
        const dy = Math.max(0, currentY - startY);
        panel.style.transform = `translate(-50%, ${Math.min(100, (dy / window.innerHeight) * 100)}%)`;
    };
    const endDrag = () => {
        if (!dragging) return;
        dragging = false;
        const dy = Math.max(0, currentY - startY);
        panel.style.transition = "";
        panel.style.transform = "";
        if (dy > Math.min(CLOSE_THRESHOLD_PX, window.innerHeight * 0.2)) close();
    };

    backdrop.addEventListener("click", () => {
        close();
    });

    const dragMove = (e) => moveDrag(e.touches ? e.touches[0].clientY : e.clientY);
    const dragEnd = () => {
        window.removeEventListener("mousemove", dragMove);
        window.removeEventListener("mouseup", dragEnd);
        window.removeEventListener("touchmove", dragMove);
        window.removeEventListener("touchend", dragEnd);
        endDrag();
    };

    panel.addEventListener(
        "touchstart",
        (e) => {
            startDrag(e.touches[0].clientY);
            window.addEventListener("touchmove", dragMove, { passive: true });
            window.addEventListener("touchend", dragEnd, { passive: true });
        },
        { passive: true }
    );

    panel.addEventListener("mousedown", (e) => {
        startDrag(e.clientY);
        window.addEventListener("mousemove", dragMove);
        window.addEventListener("mouseup", dragEnd);
    });

    const onClose = (fn) => {
        closeCallbacks.add(fn);
        return () => closeCallbacks.delete(fn);
    };
    const isOpen = () => opened;

    return { root, open, close, onClose, isOpen };
}

function setupDescriptionClamp(descEl) {
    if (!descEl) return;

    const MAX_LINES = 4;

    descEl.classList.add("product-description--clamp");
    descEl.style.setProperty("--desc-max-lines", MAX_LINES);

    requestAnimationFrame(() => {
        if (descEl.scrollHeight <= descEl.clientHeight + 1) {
            descEl.classList.remove("product-description--clamp");
            return;
        }

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "product-description-toggle";
        toggle.textContent = "ещё...";

        descEl.insertAdjacentElement("afterend", toggle);

        let expanded = false;

        toggle.addEventListener("click", () => {
            expanded = !expanded;
            if (expanded) {
                descEl.classList.add("product-description--expanded");
                toggle.textContent = "скрыть";
            } else {
                descEl.classList.remove("product-description--expanded");
                toggle.textContent = "ещё...";
            }
        });
    });
}

function setupShareButton(root, data, onec_id) {
    const shareBtn = root.querySelector(".product-share-btn");
    if (!shareBtn) return;

    shareBtn.addEventListener("click", async () => {
        const url = buildProductShareUrl(onec_id, getShareUserId());
        await shareProduct({ url });
    });
}

function getShareUserId() {
    return (
        state.user?.tg_id ||
        state.telegram?.initDataUnsafe?.user?.id ||
        sessionStorage.getItem("tg_user_id") ||
        ""
    );
}

function buildProductShareUrl(onec_id, user_id) {
    const userPart = user_id ? `&user_id=${user_id}` : "";
    return `https://t.me/elixirpeptidebot?start=product_id=${onec_id}${userPart}`;
}

async function shareProduct({ url }) {
    const shareData = { url };

    if (navigator.share) {
        try {
            await navigator.share(shareData);
            return;
        } catch (err) {
            if (err?.name === "AbortError") return;
            console.warn("Share failed, falling back:", err);
        }
    }

    if (isTelegramApp()) {
        try {
            const tgPath = `/share/url?url=${encodeURIComponent(url)}`;
            openTgLink(tgPath);
            return;
        } catch (err) {
            console.warn("Telegram share failed, falling back:", err);
        }
    }

    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(url);
            alert("Ссылка скопирована");
            return;
        }
    } catch (err) {
        console.warn("Clipboard copy failed:", err);
    }

    window.prompt("Скопируйте ссылку:", url);
}
