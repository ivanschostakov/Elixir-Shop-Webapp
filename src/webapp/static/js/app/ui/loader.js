const globalLoader = document.getElementById("global-loading-screen");

export function showLoader() { globalLoader?.classList.remove("hidden"); }
export function hideLoader() { globalLoader?.classList.add("hidden"); }

export async function withLoader(fn) {
    showLoader();
    try { return await fn(); } finally { hideLoader(); }
}
