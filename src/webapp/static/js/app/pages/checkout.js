import { showLoader, hideLoader } from "../ui/loader.js";
import { hideMainButton, isTelegramApp, showBackButton, showMainButton } from "../ui/telegram.js";
import { navigateTo } from "../router.js";
import { fetchPVZByCode, getSelectedPVZCode } from "../../services/pvzService.js";
import { YandexPvzWidget } from "./yandex-pvz-widget.js";
import {
    cartPageEl,
    checkoutPageEl,
    contactPageEl, detailEl,
    headerTitle, listEl, navBottomEl, orderDetailEl, ordersPageEl,
    paymentPageEl,
    processPaymentEl, profilePageEl,
    searchBtnEl,
    toolbarEl
} from "./constants.js";

const CDEK_ID = "cdek-map-container";
const YANDEX_ID = "yandex-map-container";
const YANDEX_LIST_ID = "yandex-list";

let _toggleLock = false;

function ensureMapContainer(id) {
    let el = document.getElementById(id);
    if (!el) {
        el = document.createElement("div");
        el.id = id;
        Object.assign(el.style, {
            width: "100%",
            height: "500px",
            marginTop: "12px",
            display: "none",
            borderRadius: "12px",
            border: "1px solid #ccc",
            overflow: "hidden",
        });
        checkoutPageEl.appendChild(el);
    }
    return el;
}

function ensureListContainer(id, afterEl) {
    let el = document.getElementById(id);
    if (!el) {
        el = document.createElement("div");
        el.id = id;
        Object.assign(el.style, {
            marginTop: "8px",
            border: "1px solid #e5e7eb",
            borderRadius: "12px",
            overflow: "hidden",
            background: "#fff",
        });
        afterEl.insertAdjacentElement("afterend", el);
    }
    return el;
}

let _ymapsReady;

async function ensureYmapsReady() {
    if (window.ymaps?.Map) {
        await new Promise((res) => ymaps.ready(res));
        return;
    }
    if (!_ymapsReady) {
        _ymapsReady = new Promise((resolve, reject) => {
            const existing = document.getElementById("ymaps-api");
            const onLoad = () => ymaps.ready(resolve);
            const onError = () => reject(new Error("Failed to load Yandex Maps"));
            if (existing) {
                existing.addEventListener("load", onLoad, {once: true});
                existing.addEventListener("error", onError, {once: true});
            } else {
                const s = document.createElement("script");
                s.id = "ymaps-api";
                s.src =
                    "https://api-maps.yandex.ru/2.1/?apikey=bb7d36f8-1e64-415c-80d2-12d77317718d&lang=ru_RU";
                s.async = true;
                s.defer = true;
                s.onload = onLoad;
                s.onerror = onError;
                document.head.appendChild(s);
            }
            setTimeout(() => reject(new Error("Yandex Maps load timeout")), 20000);
        });
    }
    await _ymapsReady;
}

function createDeliveryHeader(currentService = "CDEK") {
    document.querySelector(".delivery-toggle-container")?.remove();
    document.querySelector(".delivery-unavailable-note")?.remove();

    const header = document.createElement("div");
    header.className = "delivery-toggle-container";
    Object.assign(header.style, {
        display: "flex",
        justifyContent: "center",
        alignItems: "stretch",
        width: "100%",
        background: "#1E669E",
        borderRadius: "8px",
        overflow: "hidden",
        marginBottom: "10px",
        userSelect: "none",
        position: "relative",
        whiteSpace: "nowrap",
    });

    const makeButton = (label) => {
        const btn = document.createElement("div");
        btn.textContent = label;
        Object.assign(btn.style, {
            flex: "1 1 100%",
            textAlign: "center",
            color: "#fff",
            fontSize: "14px",
            fontWeight: "500",
            padding: "10px 0",
            cursor: "default",
            transition: "background 0.25s ease",
            background: "#17517D",
        });
        return btn;
    };

    const cdekBtn = makeButton("CDEK");
    const yandexBtn = makeButton("YANDEX");

    const indicator = document.createElement("div");
    Object.assign(indicator.style, {
        position: "absolute",
        bottom: "0",
        left: "0",
        width: "50%",
        height: "3px",
        background: "#fff",
        transition: "left 0.25s ease",
    });

    header.append(cdekBtn, yandexBtn, indicator);
    checkoutPageEl.prepend(header);

    const cdekContainer = ensureMapContainer(CDEK_ID);
    const yandexContainer = ensureMapContainer(YANDEX_ID);
    const yandexList = ensureListContainer(YANDEX_LIST_ID, yandexContainer);
    const initialService = String(currentService || "CDEK").trim().toUpperCase() === "YANDEX" ? "YANDEX" : "CDEK";

    const clearProceedSelection = () => {
        sessionStorage.removeItem("selected_delivery");
        sessionStorage.removeItem("delivery_sum");
        sessionStorage.removeItem("yandex_delivery_cost_rub");
        localStorage.removeItem("yandex_delivery_cost_rub");
        if (isTelegramApp()) hideMainButton();
        document.querySelector(".checkout-proceed-btn")?.remove();
    };

    const applyTabState = (service) => {
        const isYandex = service === "YANDEX";
        cdekBtn.style.background = isYandex ? "#17517D" : "#1E669E";
        yandexBtn.style.background = isYandex ? "#1E669E" : "#17517D";
        cdekBtn.style.cursor = isYandex ? "pointer" : "default";
        yandexBtn.style.cursor = isYandex ? "default" : "pointer";
        indicator.style.left = isYandex ? "50%" : "0";
        cdekContainer.style.display = isYandex ? "none" : "block";
        yandexContainer.style.display = isYandex ? "block" : "none";
        yandexList.style.display = isYandex ? "block" : "none";
    };

    const updateSelection = async (nextService = initialService) => {
        if (_toggleLock) return;
        _toggleLock = true;
        const service = String(nextService || "CDEK").trim().toUpperCase() === "YANDEX" ? "YANDEX" : "CDEK";
        const previousService = String(sessionStorage.getItem("selected_delivery_service") || "").trim().toUpperCase() || null;

        if (previousService && previousService !== service) clearProceedSelection();
        sessionStorage.setItem("selected_delivery_service", service);
        applyTabState(service);

        await new Promise((r) => requestAnimationFrame(r));

        try {
            if (service === "YANDEX") await initYandexWidget();
            else await initCDEKWidget();
        } finally {
            _toggleLock = false;
        }
    };

    cdekBtn.addEventListener("click", () => updateSelection("CDEK"));
    yandexBtn.addEventListener("click", () => updateSelection("YANDEX"));
    updateSelection(initialService);
}

async function initCDEKWidget(coords = [55.75, 37.61]) {
    if (!window.CDEKWidget) {
        hideLoader();
        return;
    }

    if (window.cdekWidgetInstance) {
        hideLoader();
        return window.cdekWidgetInstance;
    }

    const container = document.getElementById(CDEK_ID);
    if (!container) return;

    container.style.display = "block";
    if (!container.style.height) container.style.height = "500px";
    await new Promise((r) => requestAnimationFrame(r));

    try {
        window.cdekWidgetInstance = new window.CDEKWidget({
            root: CDEK_ID,
            apiKey: "bb7d36f8-1e64-415c-80d2-12d77317718d",
            servicePath: "api/v1/delivery/cdek",
            from: {
                city: "Уфа",
                code: 256,
                address: "ул. Революционная, 98/1 блок А",
                country_code: "RU",
                postal_code: 450078,
                coords: [54.72922108153469, 55.987779811665256],
            },
            defaultLocation: coords,
            canChoose: true,
            currency: 'RUB',
            hideFilters: {have_cashless: false, have_cash: false, is_dressing_room: false},
            hideDeliveryOptions: {office: false, door: false},
            goods: [{length: 18, width: 7, height: 24, weight: 357}],
            onReady: () => {
                container.style.display = "block";
                hideLoader();
            },
            onChoose: (mode, tariff, address) => {
                sessionStorage.setItem(
                    "selected_delivery",
                    JSON.stringify({deliveryMode: mode, tariff, address}),
                );
                if (address?.code) fetchPVZByCode(address.code);
                createProceedButton("Продолжить оформление");
            },
            tariffs: {
                door: [137],
                pickup: [368],
                office: [136],
            },
            onCalculate: async () => {
                const pvzCode = getSelectedPVZCode();
                if (pvzCode) fetchPVZByCode(pvzCode);
            },
        });
    } catch (err) {
        console.error("CDEK widget init failed:", err);
    }
    return window.cdekWidgetInstance;
}

let ydwInstance = null;

async function initYandexWidget() {
    const container = document.getElementById(YANDEX_ID);
    if (!container) return;

    container.style.display = "block";
    if (!container.style.height) container.style.height = "500px";
    await new Promise((r) => requestAnimationFrame(r));

    if (!ydwInstance) {

        await ensureYmapsReady();

        ydwInstance = new YandexPvzWidget(YANDEX_ID, {
            listContainerId: YANDEX_LIST_ID,
            radiusMeters: 12000,
            autoLocate: true,
            autoSearch: true,
            onReady: () => {
            },
            onChoose: (_pvz, payload) => {
                sessionStorage.setItem(
                    "selected_delivery",
                    JSON.stringify({
                        deliveryMode: payload.deliveryMode,
                        tariff: null,
                        address: {
                            code: payload.code,
                            address: payload.address,
                            coords: payload.coords,
                            name: payload.name,
                            phone: payload.phone,
                            schedule: payload.schedule,
                        },
                    }),
                );
                createProceedButton("Продолжить оформление");
            },
        });

        await ydwInstance.init();
    } else {

        try {

            ydwInstance.map?.container.fitToViewport?.();

            if (ydwInstance._doorPlacemark) {
                ydwInstance._doorPlacemark.balloon?.open?.();
            } else if (ydwInstance._selectedId) {
                try {
                    ydwInstance.manager?.objects.balloon.close();
                } catch {
                }
                ydwInstance.manager?.objects.balloon.open(ydwInstance._selectedId);
            }
        } catch (e) {
            console.warn("Yandex widget reopen failed, falling back to init:", e);

            try {
                await ydwInstance.init();
            } catch {
            }
        }
    }

    hideLoader();
}

export function createProceedButton(
    label = "Продолжить оформление",
    onClick = () => navigateTo("/contact"),
) {
    if (isTelegramApp()) {
        showMainButton(label, onClick);
    } else {
        let btn = document.querySelector(".checkout-proceed-btn");
        if (!btn) {
            btn = document.createElement("button");
            btn.className = "checkout-proceed-btn";
            checkoutPageEl.appendChild(btn);
        }
        btn.textContent = label;
        btn.onclick = onClick;
    }
}

export async function renderCheckoutPage() {
    showLoader();
    showBackButton();
    cartPageEl.style.display = "none";
    detailEl.style.display = "none";
    listEl.style.display = "none";
    toolbarEl.style.display = "none";
    contactPageEl.style.display = "none";
    searchBtnEl.style.display = "none";
    headerTitle.textContent = "Доставка";
    paymentPageEl.style.display = "none";
    processPaymentEl.style.display = "none";
    navBottomEl.style.display = "none";
    profilePageEl.style.display = "none";
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "none";
    checkoutPageEl.style.display = "block";
    await new Promise((r) => requestAnimationFrame(r));

    createDeliveryHeader(sessionStorage.getItem("selected_delivery_service") || "CDEK");
    console.log("✅ Checkout initialized");
}
