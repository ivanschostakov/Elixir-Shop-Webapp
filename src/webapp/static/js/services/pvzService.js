import { apiGet } from "./api.js";

export function getSelectedPVZCode() {
    const elements = document.querySelectorAll(".cdek-1smek3");
    for (const element of elements) {
        const match = element.textContent.trim().match(/- (\S+)$/);
        if (match) return match[1];
    }
    return null;
}

export async function fetchPVZByCode(code) {
    if (!code) return null;
    try {
        const data = await apiGet(`/delivery/cdek?action=offices&code=${encodeURIComponent(code)}`);
        if (!Array.isArray(data) || !data.length) return null;
        renderPVZInfo(data[0]);
        return data[0];
    } catch (err) {
        console.error("❌ Error fetching PVZ info:", err);
        return null;
    }
}

export function renderPVZInfo(pvz) {
    if (!pvz) return;
    let infoDiv = document.querySelector(".my-pvz-info");
    if (!infoDiv) {
        infoDiv = document.createElement("div");
        infoDiv.className = "my-pvz-info";
        infoDiv.style.marginTop = "10px";
        infoDiv.style.fontSize = "14px";
        infoDiv.style.color = "#333";
        const container = document.querySelector(".cdek-2ew9g8");
        if (!container) return;
        container.appendChild(infoDiv);
    }
    infoDiv.innerHTML = `
    ${pvz.phones?.length ? `<p><b>Телефон:</b> ${pvz.phones.map(p => p.number).join(", ")}</p>` : ""}
    ${pvz.email ? `<p><b>Email:</b> ${pvz.email}</p>` : ""}
    ${pvz.note ? `<p><b>Примечание:</b> ${pvz.note}</p>` : ""}
  `;
}
