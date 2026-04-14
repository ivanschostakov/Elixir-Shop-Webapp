import { withLoader } from "../ui/loader.js";
import { apiGet, apiPost } from "../../services/api.js";

const SUGGEST_ROW_HEIGHT = 36;
const DEFAULT_CENTER = [55.751, 37.618];
const DEFAULT_ZOOM = 4;

export class YandexPvzWidget {
    constructor(containerId, options = {}) {
        this.root = document.getElementById(containerId);
        if (!this.root) {
            console.error(`YandexPvzWidget: #${containerId} не найден`);
            return;
        }

        this.options = {
            dataUrl: "/delivery/yandex/get-pvz-all",
            calculateUrl: "/delivery/yandex/calculate",
            availabilityUrl: "/delivery/yandex/availability",
            costStorageKey: "yandex_delivery_cost_rub",
            getOrderData: null,
            defaultCenter: DEFAULT_CENTER,
            defaultZoom: DEFAULT_ZOOM,
            autoLocate: false,
            onReady: null,
            onChoose: null,
            ...options,
        };

        this.map = null;
        this.manager = null;

        this._pointsById = new Map();
        this._selectedId = null;

        this._doorPlacemark = null;
        this._doorAddress = "";
        this._doorSeq = 0;

        this._geocodeCache = new Map();
        this._geocodeCacheMax = 50;

        this.preset = { default: "islands#blueDotIcon", active: "islands#redDotIcon" };

        this._renderLayout();
        this._bindSearchUI();
    }

    _renderLayout() {
        this.root.innerHTML = `
            <div class="ydw-toolbar" style="display:flex;flex-direction:column;gap:8px;margin-bottom:.5rem;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <input id="ydw-query" type="text" inputmode="search" placeholder="Введите населённый пункт"
                           style="flex:1;padding:.5rem .6rem;border:1px solid #ddd;border-radius:8px;">
                </div>

                <div id="ydw-suggest"
                     style="display:none;height:${SUGGEST_ROW_HEIGHT * 5}px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:8px;background:#fff;"></div>

                <!-- ✅ Стоимость доставки (ТОЛЬКО цена) -->
                <div id="ydw-cost"
                     style="display:none;border:1px solid #e5e7eb;background:#fff;border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.35;"></div>
            </div>

            <div id="ydw-map" style="width:100%;height:100%;min-height:400px;border-radius:8px;"></div>`;

        this.mapEl = this.root.querySelector("#ydw-map");
        this.queryEl = this.root.querySelector("#ydw-query");
        this.suggestEl = this.root.querySelector("#ydw-suggest");
        this.costEl = this.root.querySelector("#ydw-cost");

        this.root.addEventListener("click", (e) => {
            const btn = e.target.closest(".ydw-choose-btn");
            if (!btn) return;

            const id = btn.getAttribute("data-id");
            if (!id) return;

            (async () => {
                btn.textContent = "⏳ Проверяю доставку...";
                btn.disabled = true;
                btn.style.opacity = "0.8";
                btn.style.cursor = "default";

                this._select(id, false);

                const ok = await this._checkAvailabilityForSelectedPVZ();
                if (!ok) {
                    btn.textContent = "❌ Недоступно";
                    return;
                }

                btn.textContent = "⏳ Считаю доставку...";
                await this._emitChoosePVZ();

                btn.textContent = "✅ Выбрано";
            })();
        });
    }

    async init(center = this.options.defaultCenter, zoom = this.options.defaultZoom) {
        this.map = new ymaps.Map(
            this.mapEl,
            { center, zoom, controls: ["zoomControl", "fullscreenControl"] },
            { suppressMapOpenBlock: true, yandexMapDisablePoiInteractivity: true }
        );

        this.manager = new ymaps.ObjectManager({ clusterize: true, gridSize: 64, clusterDisableClickZoom: false });
        this.manager.objects.options.set("preset", this.preset.default);
        this.manager.clusters.options.set("preset", "islands#invertedBlueClusterIcons");
        this.map.geoObjects.add(this.manager);

        this.manager.objects.events.add("click", (e) => {
            const id = e.get("objectId");
            this._removeDoorPlacemark();
            this._select(id, true);
        });

        this.map.events.add("click", (e) => {
            if (e.get("target") !== this.map) return;
            const coords = e.get("coords");
            this._clearSelection();
            this._setDoorPlacemark(coords);
        });

        const all = await withLoader(async () => {
            try {
                const data = await apiGet(this.options.dataUrl);
                return data ?? { points: [] };
            } catch {
                return { points: [] };
            }
        });

        const src = Array.isArray(all?.points) ? all.points : (Array.isArray(all) ? all : []);
        const points = src.map((p) => this._normalizePoint(p));
        this._drawPoints(points);

        if (points.length) {
            try {
                const coords = points.map((p) => p.coords);
                const bounds = ymaps.util.bounds.fromPoints(coords);
                this.map.setBounds(bounds, { checkZoomRange: true, zoomMargin: 32 });
            } catch {}
        } else {
            this._toast("Нет пунктов выдачи для отображения");
        }

        if (this.options.autoLocate && navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    const coords = [pos.coords.latitude, pos.coords.longitude];
                    this.map?.panTo(coords, { duration: 300 });
                },
                () => {},
                { enableHighAccuracy: true, maximumAge: 60_000, timeout: 5_000 }
            );
        }

        this.options.onReady?.();
    }

    _bindSearchUI() {
        const debounce = (fn, delay = 300) => {
            let t;
            return (...a) => {
                clearTimeout(t);
                t = setTimeout(() => fn(...a), delay);
            };
        };

        this._searchVariants = [];
        this._suggestActive = -1;

        this.queryEl?.addEventListener(
            "input",
            debounce(async (e) => {
                const q = e.target.value.trim();
                if (!q) {
                    this._searchVariants = [];
                    this._renderSuggest([]);
                    return;
                }
                const variants = await this._geocodeLocality(q);
                this._searchVariants = Array.isArray(variants) ? variants : [];
                this._renderSuggest(this._searchVariants);
                this._suggestActive = -1;
            }, 250)
        );

        this.suggestEl?.addEventListener("click", (e) => {
            const row = e.target.closest(".ydw-suggest-row");
            this.queryEl.value = "";
            if (!row) return;
            const idx = Number(row.getAttribute("data-index") || "-1");
            const item = this._searchVariants?.[idx];
            if (!item?.coords) return;
            this._goToVariant(item);
        });

        this.queryEl?.addEventListener("keydown", (e) => {
            if (!this._searchVariants.length) return;

            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                const max = this._searchVariants.length - 1;
                if (e.key === "ArrowDown") this._suggestActive = Math.min(max, this._suggestActive + 1);
                else this._suggestActive = Math.max(0, this._suggestActive < 0 ? 0 : this._suggestActive - 1);
                this._highlightSuggest(this._suggestActive);
            } else if (e.key === "Enter") {
                e.preventDefault();
                const idx = this._suggestActive >= 0 ? this._suggestActive : 0;
                const item = this._searchVariants[idx];
                if (item) this._goToVariant(item);
            } else if (e.key === "Escape") {
                this._renderSuggest([]);
            }
        });
    }

    _goToVariant(item) {
        if (item.bounds) this.map?.setBounds(item.bounds, { checkZoomRange: true, zoomMargin: 32 });
        else this.map?.panTo(item.coords, { duration: 300 });
        this._renderSuggest([]);
    }

    _highlightSuggest(activeIdx) {
        if (!this.suggestEl) return;
        [...this.suggestEl.children].forEach((el, i) => (el.style.background = i === activeIdx ? "#eef2ff" : ""));
        const target = this.suggestEl.children[activeIdx];
        if (target) target.scrollIntoView({ block: "nearest" });
    }

    _renderSuggest(variants) {
        if (!this.suggestEl) return;
        if (!Array.isArray(variants) || variants.length === 0) {
            this.suggestEl.style.display = "none";
            this.suggestEl.innerHTML = "";
            return;
        }

        const frag = document.createDocumentFragment();
        variants.forEach((v, i) => {
            const row = document.createElement("div");
            row.className = "ydw-suggest-row";
            row.setAttribute("data-index", String(i));
            row.style.cssText = `
              display:flex;align-items:center;height:${SUGGEST_ROW_HEIGHT}px;padding:0 10px;
              cursor:pointer;border-bottom:1px solid #f0f0f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;user-select:none;
            `;
            row.addEventListener("mouseenter", () => (row.style.background = "#f8fafc"));
            row.addEventListener("mouseleave", () => (row.style.background = ""));

            const name = (v.name || "").toString();
            const kind = (v.kind || "").toString();

            row.innerHTML = `
              <div style="font-size:13px;flex:1;min-width:0;">
                ${this._escape(name)}
                ${kind ? `<span style="opacity:.65;font-size:12px;margin-left:6px;">(${this._escape(kind)})</span>` : ""}
              </div>
            `;
            frag.appendChild(row);
        });

        this.suggestEl.innerHTML = "";
        this.suggestEl.appendChild(frag);
        this.suggestEl.style.height = `${SUGGEST_ROW_HEIGHT * 5}px`;
        this.suggestEl.style.display = "block";
    }

    async _geocodeLocality(query) {
        if (this._geocodeCache.has(query)) return this._geocodeCache.get(query);
        try {
            const res = await ymaps.geocode(query, { results: 50 });
            const gos = res.geoObjects;
            if (!gos || gos.getLength() === 0) {
                this._rememberGeocode(query, []);
                return [];
            }
            const variants = [];
            for (let i = 0; i < gos.getLength(); i++) {
                const g = gos.get(i);
                const meta = g.properties.get("metaDataProperty")?.GeocoderMetaData;
                variants.push({
                    name: g.getAddressLine(),
                    kind: meta?.kind,
                    coords: g.geometry.getCoordinates(),
                    bounds: g.properties.get("boundedBy"),
                });
            }
            this._rememberGeocode(query, variants);
            return variants;
        } catch {
            this._rememberGeocode(query, []);
            return [];
        }
    }

    _rememberGeocode(q, val) {
        this._geocodeCache.set(q, val);
        if (this._geocodeCache.size > this._geocodeCacheMax) {
            const firstKey = this._geocodeCache.keys().next().value;
            this._geocodeCache.delete(firstKey);
        }
    }

    async _setDoorPlacemark(coords) {
        const mySeq = ++this._doorSeq;

        const prev = this._doorPlacemark || null;
        const address = (await this._resolveAddress(coords)) || "Адрес не определён";
        if (mySeq !== this._doorSeq) return;

        this._doorAddress = address;
        const html = this._doorBalloonHtml(address);

        const fresh = new ymaps.Placemark(
            coords,
            { hintContent: address, balloonContent: html },
            { preset: "islands#redIcon", draggable: true }
        );
        try {
            fresh.properties.set("ydwDoor", true);
        } catch {}

        fresh.events.add("dragend", async () => {
            const newCoords = fresh.geometry.getCoordinates();
            await this._setDoorPlacemark(newCoords);
        });

        this.map.geoObjects.add(fresh);
        this._doorPlacemark = fresh;
        try {
            fresh.balloon.open();
        } catch {}
        this._wireDoorChooseOnce(coords);

        if (prev && prev !== fresh) {
            try {
                prev.balloon?.close?.();
            } catch {}
            try {
                this.map.geoObjects.remove(prev);
            } catch {}
        }

        this._purgeOldDoorPlacemarks(fresh);
        this.map?.panTo(coords, { duration: 300 });
    }

    _wireDoorChooseOnce(coords) {
        const onceHandler = (e) => {
            const btn = e.target.closest(".ydw-choose-door");
            if (!btn) return;
            e.stopPropagation();

            (async () => {
                btn.textContent = "⏳ Проверяю доставку...";
                btn.disabled = true;
                btn.style.opacity = "0.8";
                btn.style.cursor = "default";

                const ok = await this._checkAvailability({
                    delivery_mode: "time_interval",
                    destination: {
                        full_address: this._doorAddress || "",
                        latitude: Number(coords?.[0]),
                        longitude: Number(coords?.[1]),
                    },
                    send_unix: true,
                });

                if (!ok) {
                    btn.textContent = "❌ Недоступно";
                    return;
                }

                btn.textContent = "⏳ Считаю доставку...";
                const basePayload = { deliveryMode: "time_interval", coords, address: this._doorAddress || "" };
                const enriched = await this._calcDelivery(basePayload);

                btn.textContent = "✅ Выбрано";
                this.options.onChoose?.(null, enriched);
            })();
        };

        this.root.addEventListener("click", onceHandler, { once: true });
    }

    async _resolveAddress(coords) {
        const [lat, lon] = coords;

        try {
            const res = await apiGet(`/delivery/yandex/reverse-geocode?lat=${lat}&lon=${lon}`);

            if (res && typeof res === "object" && typeof res.json === "function") {
                const data = await res.json().catch(() => ({}));
                if (data?.formatted) return data.formatted;
            } else {
                if (res?.formatted) return res.formatted;
            }
        } catch {}

        try {
            const g = await ymaps.geocode(coords, { results: 1 });
            const first = g.geoObjects.get(0);
            return first?.getAddressLine?.() || "";
        } catch {}

        return "";
    }

    _doorBalloonHtml(address) {
        return `
        <div style="font-size:13px;line-height:1.35;max-width:260px">
            <div style="font-weight:600;margin-bottom:4px">Доставка курьером</div>
            <div style="margin-bottom:6px">${this._escape(address)}</div>
            <div style="margin-top:8px;display:flex;gap:8px;justify-content:flex-end">
                <button class="ydw-choose-door"
                        style="padding:6px 10px;border:0;border-radius:8px;background:#ef4444;color:#fff;cursor:pointer;">
                    Выбрать этот адрес
                </button>
            </div>
        </div>
        `;
    }

    _removeDoorPlacemark() {
        if (this._doorPlacemark) {
            try {
                this.map.geoObjects.remove(this._doorPlacemark);
            } catch {}
            this._doorPlacemark = null;
            this._doorAddress = "";
        }
    }

    _purgeOldDoorPlacemarks(keep) {
        if (!this.map) return;
        try {
            this.map.geoObjects.each((obj) => {
                if (obj && obj.properties && obj.properties.get("ydwDoor") && obj !== keep) {
                    try {
                        obj.balloon?.close?.();
                    } catch {}
                    try {
                        this.map.geoObjects.remove(obj);
                    } catch {}
                }
            });
        } catch {}
    }

    _normalizePoint(p) {
        const safeId = `pvz_${p.id}`;
        const addr = p.address ?? {};
        return {
            id: safeId,
            rawId: p.id,
            coords: [p.position.latitude, p.position.longitude],
            name: p.name ?? "Пункт выдачи заказов",
            phone: p.contact?.phone ?? "",
            schedule: this._formatSchedule(p.schedule),
            dayoffs: this._formatDayoffs(p.dayoffs),
            address: addr.full_address || [addr.region, addr.locality, addr.street, addr.house].filter(Boolean).join(", "),
        };
    }

    _drawPoints(points) {
        this._pointsById.clear();
        this.manager.removeAll();
        if (!Array.isArray(points) || !points.length) return;

        const features = points.map((p) => {
            this._pointsById.set(p.id, p);
            return {
                type: "Feature",
                id: p.id,
                geometry: { type: "Point", coordinates: p.coords },
                properties: { hintContent: p.name, balloonContent: this._balloonHtml(p) },
            };
        });

        this.manager.add({ type: "FeatureCollection", features });
    }

    _balloonHtml(p) {
        return `
            <div style="font-size:13px;line-height:1.35;max-width:260px">
              <div style="font-weight:600;margin-bottom:4px">${this._escape(p.name)}</div>
              <div style="margin-bottom:6px">${this._escape(p.address)}</div>

              ${p.phone ? `<div style="margin-bottom:4px">☎ ${this._escape(p.phone)}</div>` : ""}
              ${p.schedule ? `<div style="margin-bottom:4px">🕒 ${this._escape(p.schedule)}</div>` : ""}
              ${p.dayoffs ? `<div style="margin-bottom:4px">❌ ${this._escape(p.dayoffs)}</div>` : ""}

              <div style="margin-top:8px;display:flex;justify-content:flex-end">
                <button class="ydw-choose-btn" data-id="${this._escape(p.id)}"
                        style="padding:6px 10px;border:0;border-radius:8px;background:#10b981;color:#fff;cursor:pointer;">
                  Выбрать
                </button>
              </div>
            </div>
          `;
    }

    _select(id, openBalloon = false) {
        if (id && !String(id).startsWith("pvz_")) id = `pvz_${id}`;
        if (!this._pointsById.has(id)) return;

        const prev = this._selectedId;
        if (prev === id) return;

        this._removeDoorPlacemark();
        this._clearCost();

        if (this.manager) {
            if (prev) this.manager.objects.setObjectOptions(prev, { preset: this.preset.default });
            this.manager.objects.setObjectOptions(id, { preset: this.preset.active });
        }

        const p = this._pointsById.get(id);
        this.map?.panTo(p.coords, { duration: 300 });
        this._selectedId = id;

        if (openBalloon) {
            try {
                this.manager.objects.balloon.close();
            } catch {}
            setTimeout(() => this.manager.objects.balloon.open(id), 0);
        }
    }

    _clearSelection() {
        this._clearCost();
        const prev = this._selectedId;
        if (prev && this.manager) this.manager.objects.setObjectOptions(prev, { preset: this.preset.default });
        this._selectedId = null;
        try {
            this.manager?.objects?.balloon?.close();
        } catch {}
    }

    async _checkAvailabilityForSelectedPVZ() {
        const p = this._pointsById.get(this._selectedId);
        if (!p) return false;

        return await this._checkAvailability({
            delivery_mode: "self_pickup",
            destination: { platform_station_id: String(p.rawId) },
            send_unix: true,
        });
    }

    async _emitChoosePVZ() {
        const p = this._pointsById.get(this._selectedId);
        if (!p) return;

        const basePayload = {
            deliveryMode: "self_pickup",
            code: p.rawId,
            name: p.name,
            coords: p.coords,
            address: p.address,
            phone: p.phone,
            schedule: p.schedule,
            dayoffs: p.dayoffs,
        };

        const enriched = await this._calcDelivery(basePayload);
        this.options.onChoose?.(p, enriched);
    }

    async _checkAvailability(body) {
        const result = await withLoader(async () => {
            try {
                const res = await apiPost(this.options.availabilityUrl, body);

                if (res && typeof res === "object" && typeof res.json === "function") {
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) return { ok: false, deliverable: false, detail: data?.detail || data };
                    return data;
                }

                return res ?? {};
            } catch (e) {
                return { ok: false, deliverable: false, detail: String(e?.message || e) };
            }
        });

        const deliverable = Boolean(result?.deliverable);

        if (!deliverable) {
            this._clearCost();
            alert("Доставка невозможна по адресу");
            return false;
        }

        let costRub = null;

        if (result?.nearest && result.nearest.price_rub != null) {
            const n = Number(result.nearest.price_rub);
            if (Number.isFinite(n)) costRub = n;
        }

        if (costRub == null) {
            const s = (result?.nearest?.pricing_total ?? "").toString().trim();
            const m = s.match(/(\d+(?:[.,]\d+)?)/);
            if (m) {
                const v = Number(m[1].replace(",", "."));
                if (Number.isFinite(v)) costRub = Math.round(v);
            }
        }

        this._setCost(costRub);
        return true;
    }

    async _calcDelivery(destinationPayload) {
        const order = (typeof this.options.getOrderData === "function" ? this.options.getOrderData() : null) || null;

        const body = {
            delivery_mode: destinationPayload.deliveryMode,
            destination: {
                platform_station_id: destinationPayload.deliveryMode === "self_pickup" ? String(destinationPayload.code ?? "") : null,
                address: destinationPayload.deliveryMode === "time_interval" ? String(destinationPayload.address ?? "") : null,
            },
            total_weight: Number(order?.total_weight || 0),
            total_assessed_price: Number(order?.total_assessed_price || 0),
            client_price: Number(order?.client_price || 0),
            payment_method: order?.payment_method || "already_paid",
            places: Array.isArray(order?.places) ? order.places : [],
            is_oversized: Boolean(order?.is_oversized || false),
            send_unix: order?.send_unix !== undefined ? Boolean(order.send_unix) : true,
        };

        const calc = await withLoader(async () => {
            try {
                const r = await apiPost(this.options.calculateUrl, body);

                if (r && typeof r === "object" && typeof r.json === "function") {
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) throw new Error(data?.detail || "calculate failed");
                    return data;
                }

                const data = r ?? {};
                if (!data?.ok && data?.error) throw new Error(data.error);
                return data;
            } catch (e) {
                return { ok: false, error: String(e?.message || e) };
            }
        });

        return { ...destinationPayload, calc };
    }

    _setCost(costRub) {
        const n = Number(costRub);
        if (!Number.isFinite(n) || n <= 0) {
            this._clearCost();
            return;
        }

        if (this.costEl) {
            this.costEl.innerHTML = `💰 Стоимость доставки: <b>${Math.round(n)} ₽</b>`;
            this.costEl.style.display = "block";
        }

        try {
            localStorage.setItem(this.options.costStorageKey, String(Math.round(n)));
        } catch {}
    }

    _clearCost() {
        if (this.costEl) {
            this.costEl.style.display = "none";
            this.costEl.innerHTML = "";
        }
        try {
            localStorage.removeItem(this.options.costStorageKey);
        } catch {}
    }

    _formatSchedule(schedule) {
        if (!schedule?.restrictions?.length) return "";
        const dayNames = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
        const pad = (n) => String(n).padStart(2, "0");
        const fmt = (t) => `${pad(t?.hours ?? 0)}:${pad(t?.minutes ?? 0)}`;
        return schedule.restrictions
            .map((r) => {
                const days = (r.days ?? []).map((d) => dayNames[d - 1]).join(", ");
                return `${days || "—"}: ${fmt(r.time_from)}–${fmt(r.time_to)}`;
            })
            .join(" · ");
    }

    _formatDayoffs(dayoffs) {
        if (!Array.isArray(dayoffs) || !dayoffs.length) return "";
        const opts = { day: "2-digit", month: "2-digit" };
        const formatted = dayoffs
            .map((d) => {
                const dt = d.date_utc ? new Date(d.date_utc) : new Date((d.date ?? 0) * 1000);
                return isNaN(dt) ? "" : dt.toLocaleDateString("ru-RU", opts);
            })
            .filter(Boolean);
        return formatted.length ? `Выходные: ${formatted.join(", ")}` : "";
    }

    _escape(s) {
        return String(s ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    _toast(msg) {
        console.info(msg);
    }

    destroy() {
        this._clearCost();
        this._removeDoorPlacemark();
        try {
            this.manager?.removeAll();
        } catch {}
        try {
            this.map?.destroy?.();
        } catch {}
        this.map = null;
        this.manager = null;
        this.root.innerHTML = "";
    }
}
