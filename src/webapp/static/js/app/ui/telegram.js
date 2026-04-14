import { state } from "../state.js";
import { navigateTo } from "../router.js";
import { getCurrentPathFromHash, updateBottomNavActive } from "./nav-bottom.js";

const tg = state.telegram;
tg?.enableClosingConfirmation();
let mainButtonHandler = null;
let backButtonHandler = null;

function detachMainButtonHandler() {
    if (!mainButtonHandler) return;
    try { tg?.offEvent?.("mainButtonClicked", mainButtonHandler); } catch (error) { console.warn("[TG] offEvent(mainButtonClicked) failed:", error); }
    mainButtonHandler = null;
}

function detachBackButtonHandler() {
    if (!backButtonHandler) return;
    try { tg?.offEvent?.("backButtonClicked", backButtonHandler); } catch {}
    backButtonHandler = null;
}

function syncNavAfterHistoryBack() {
    const path = getCurrentPathFromHash();
    updateBottomNavActive(path);
    if (path.includes("checkout")) hideMainButton();
}

export function isTelegramApp() {
    if (!tg) return false;
    const user = tg.initDataUnsafe?.user;
    const hasValidUser = user && typeof user.id === "number";
    const realPlatform = tg.platform && tg.platform !== "unknown";
    return Boolean(hasValidUser && realPlatform);
}

export function showMainButton(text, onClick) {
    if (!isTelegramApp() || !tg?.MainButton) return () => {};
    detachMainButtonHandler();
    mainButtonHandler = onClick;
    tg.MainButton.hideProgress();
    tg.MainButton.enable();
    tg.MainButton.setText(text);
    tg.MainButton.show();
    tg.onEvent?.("mainButtonClicked", mainButtonHandler);
    return () => {
        if (mainButtonHandler !== onClick) return;
        hideMainButton();
    };
}

export function updateMainButton(text, disable, progress) {
    if (!isTelegramApp() || !tg?.MainButton) return;
    if (typeof text === "string") tg.MainButton.setText(text);
    if (progress === true) tg.MainButton.showProgress();
    if (progress === false) tg.MainButton.hideProgress();
    if (disable === true) tg.MainButton.disable();
    if (disable === false) tg.MainButton.enable();
}

export function hideMainButton() {
    if (!isTelegramApp() || !tg?.MainButton) return;
    detachMainButtonHandler();
    tg.MainButton.hide();
    tg.MainButton.hideProgress();
    tg.MainButton.enable();
}

export function hideBackButton() {
    if (!isTelegramApp() || !tg?.BackButton) return;
    detachBackButtonHandler();
    tg.BackButton.hide();
}

export function showBackButton(onClick) {
    if (!isTelegramApp() || !tg?.BackButton) return () => {};
    detachBackButtonHandler();
    const defaultHandler = () => {
        if (window.history.length <= 1) {
            navigateTo("/");
            return;
        }
        window.history.back();
        setTimeout(syncNavAfterHistoryBack, 0);
    };
    const handler = onClick || defaultHandler;
    backButtonHandler = handler;
    tg.BackButton.show();
    tg.onEvent?.("backButtonClicked", handler);
    return () => {
        if (backButtonHandler !== handler) return;
        hideBackButton();
    };
}

export function openTgLink(pathFull) {
    const mobileData = JSON.stringify({ path_full: pathFull });
    const webData = JSON.stringify({ eventType: "web_app_open_tg_link", eventData: { path_full: pathFull } });
    if (window.TelegramWebviewProxy && typeof window.TelegramWebviewProxy.postEvent === "function") {
        window.TelegramWebviewProxy.postEvent("web_app_open_tg_link", mobileData);
        return;
    }
    if (!window.parent) return;
    window.parent.postMessage(webData, "https://web.telegram.org");
}

export function launchConfettiBurst() {
    if (typeof confetti !== "function") return;
    confetti({ particleCount: 140, spread: 70, startVelocity: 45, origin: { y: 0.6 } });
    setTimeout(() => confetti({ particleCount: 100, spread: 100, startVelocity: 35, origin: { y: 0.4 } }), 250);
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred("rigid"); } catch {}
}
