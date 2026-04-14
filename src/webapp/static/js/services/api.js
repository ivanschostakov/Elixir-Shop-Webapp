const API_BASE = "/api/v1";
const WEBAPP_ORIGIN = "https://elixirpeptides.devsivanschostakov.org";
const ABSOLUTE_URL_RE = /^https?:\/\//i;

function normalizePath(path) {
    if (!path.startsWith("/")) return `/${path}`;
    return path;
}

function buildUrl(path) {
    if (path.startsWith(WEBAPP_ORIGIN)) return `${WEBAPP_ORIGIN}${API_BASE}${normalizePath(path.slice(WEBAPP_ORIGIN.length))}`;
    if (ABSOLUTE_URL_RE.test(path)) return path;
    return `${API_BASE}${normalizePath(path)}`;
}

async function parseResponseBody(response) {
    const text = await response.text();
    if (!text) return null;
    try { return JSON.parse(text); } catch { return text; }
}

function formatErrorPart(value) {
    if (value == null) return "";
    if (typeof value === "string") return value.trim();
    if (typeof value === "number" || typeof value === "boolean") return String(value);

    if (Array.isArray(value)) {
        return value
            .map((item) => formatErrorPart(item))
            .filter(Boolean)
            .join("\n");
    }

    if (typeof value === "object") {
        if (Array.isArray(value.loc) && value.msg) {
            const location = value.loc.filter((part) => part !== "body").join(".");
            return location ? `${location}: ${value.msg}` : String(value.msg).trim();
        }

        for (const key of ["reason", "message", "error", "detail"]) {
            const formatted = formatErrorPart(value[key]);
            if (formatted) return formatted;
        }
    }

    return "";
}

function getErrorMessage(body, status) {
    const formatted = formatErrorPart(body);
    return formatted || `HTTP ${status}`;
}

async function apiRequest(method, path, data) {
    const response = await fetch(buildUrl(path), {
        method,
        credentials: "same-origin",
        headers: data === undefined ? {} : { "Content-Type": "application/json" },
        body: data === undefined ? undefined : JSON.stringify(data),
    });
    const body = await parseResponseBody(response);
    if (!response.ok) {
        const error = new Error(getErrorMessage(body, response.status));
        error.status = response.status;
        error.body = body;
        error.path = path;
        error.method = method;
        throw error;
    }
    return body;
}

export async function apiGet(path) { return apiRequest("GET", path); }
export async function apiPost(path, data) { return apiRequest("POST", path, data); }
export async function apiPut(path, data) { return apiRequest("PUT", path, data); }
export async function apiPatch(path, data) { return apiRequest("PATCH", path, data); }
export async function apiDelete(path, data) { return apiRequest("DELETE", path, data); }
export { API_BASE };
