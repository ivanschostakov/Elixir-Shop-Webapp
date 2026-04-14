import { apiGet } from "./api.js";

function toCsv(value) {
    if (!Array.isArray(value)) return String(value ?? "").trim();
    return value.map((item) => String(item).trim()).filter(Boolean).join(",");
}

function isAllowedSortBy(value) { return value === "name" || value === "price"; }
function isAllowedSortDir(value) { return value === "asc" || value === "desc"; }
function isAllowedCategoryMode(value) { return value === "any" || value === "all"; }

export async function searchProducts({ q = "", page = 0, limit, tgCategoryIds, tgCategoryMode = "any", sortBy = "name", sortDir = "asc" } = {}) {
    const params = new URLSearchParams();
    params.set("q", q ?? "");
    params.set("page", String(page ?? 0));
    if (limit != null) params.set("limit", String(limit));
    if (tgCategoryIds != null) {
        const csv = toCsv(tgCategoryIds);
        if (csv) params.set("tg_category_ids", csv);
    }
    if (isAllowedCategoryMode(tgCategoryMode)) params.set("tg_category_mode", tgCategoryMode);
    if (isAllowedSortBy(sortBy)) params.set("sort_by", sortBy);
    if (isAllowedSortDir(sortDir)) params.set("sort_dir", sortDir);
    return apiGet(`/search/products?${params.toString()}`);
}

export async function getProductDetail(onecId) { return apiGet(`/product/${onecId}/json`); }
