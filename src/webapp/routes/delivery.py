import json
import logging
import re
import time
import httpx

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import Response

from config import CDEK_API_URL, YANDEX_GEOCODER_TOKEN, YANDEX_DELIVERY_TOKEN, YANDEX_DELIVERY_BASE_URL, YANDEX_DELIVERY_WAREHOUSE_ID
from src.services.cdek import client as cdek_client
from src.webapp.schemas import AvailabilityRequest

logger = logging.getLogger("delivery-services")
cdek_router = APIRouter(prefix="/delivery/cdek", tags=["cdek"])
yandex_router = APIRouter(prefix="/delivery/yandex", tags=["yandex"])

@cdek_router.api_route(path="", methods=["GET", "POST"])
async def cdek_proxy(request: Request):
    headers = {"Authorization": f"Bearer {cdek_client._access_token}"}
    params = request.query_params
    raw_body = await request.body()
    raw_body = raw_body.decode(encoding="utf-8")
    body = json.loads(raw_body) if raw_body else {}
    method = request.method

    action = params.get("action") or body.get("action")
    if action == "offices": endpoint = f"{CDEK_API_URL}/deliverypoints"
    elif action == "calculate":
        if isinstance(body, dict) and isinstance(body.get("to_location"), dict):
            endpoint = f"{CDEK_API_URL}/calculator/tarifflist"
            body.update({"type": 2})
        else: return Response(status_code=400, content='{"error":"Invalid to_location"}')
    else: return Response(status_code=400, content='{"error":"Unknown action"}')

    timeout = httpx.Timeout(connect=5, read=15, write=10, pool=5)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method == "GET": resp = await client.get(endpoint, params=params, headers=headers)
        else: resp = await client.post(endpoint, content=raw_body, headers={**headers, "Content-Type": "application/json"})


    if action == "calculate" and resp.status_code == 200:
        try:
            data = resp.json()
            return Response(content=json.dumps(data, ensure_ascii=False), status_code=200, media_type="application/json")
        except Exception as e: logger.warning("CDEK: Error filtering tariffs: %s", e)

    logger.debug("CDEK %s request completed with status %s", action, resp.status_code)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@yandex_router.get("/reverse-geocode")
async def reverse_geocode(lat: float = Query(...), lon: float = Query(...)):
    if not YANDEX_GEOCODER_TOKEN: raise HTTPException(status_code=512, detail='YANDEX TOKEN NOT CONFIGURED')

    geo_url = "https://geocode-maps.yandex.ru/1.x/"
    geo_params = {
        "apikey": YANDEX_GEOCODER_TOKEN,
        "geocode": f"{lon},{lat}",
        "format": "json",
        "lang": "ru_RU",
        "results": 5,
    }
    timeout = httpx.Timeout(connect=5, read=15, write=10, pool=5)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(geo_url, params=geo_params)
        r.raise_for_status()
        data = r.json()

    try:
        members = data["response"]["GeoObjectCollection"]["featureMember"]
        first = members[0]["GeoObject"]
        address = first["metaDataProperty"]["GeocoderMetaData"]["Address"]
        comps = address["Components"]
        country_code = address["country_code"]
        formatted = address["formatted"]
        city_name = next((c["name"] for c in comps if c.get("kind") == "locality"), None) or "Москва"
    except Exception:
        city_name = "Москва"
        country_code = 'RU'
        formatted = "Улица Пушкина, дом Колотушина"

    if not YANDEX_DELIVERY_TOKEN: return {"city": city_name, "variants": []}

    detect_url = f"{YANDEX_DELIVERY_BASE_URL}/api/b2b/platform/location/detect"
    headers = {
        "Authorization": f"Bearer {YANDEX_DELIVERY_TOKEN}",
        "Content-Type": "application/json",
        "Accept-Language": "ru/ru",
    }
    payload = {"location": city_name}

    variants_out = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(detect_url, json=payload, headers=headers)
            resp.raise_for_status()
            ddata = resp.json()
            raw = ddata.get("variants") or []
            for v in raw:
                geo_id = v.get("geo_id")
                address = v.get("address") or ""
                if geo_id is None: continue
                variants_out.append({"geo_id": int(geo_id), "address": address})
        except Exception as e:
            logger.warning("REVERSE_GEOCODE: location/detect failed for %s: %s", city_name, e)
            variants_out = []

    return {"city": city_name, "country_code": country_code, "formatted": formatted, "variants": variants_out}

@yandex_router.post("/get-pvz")
async def get_pvz(req: dict):
    """
    Unified Yandex PVZ fetcher.

    Accepts either:
    • geo_id — exact city;
    • latitude/longitude as intervals (each with 'from'/'to');
    • latitude + longitude + radius (meters) — fallback.
    """

    if not YANDEX_DELIVERY_TOKEN: raise HTTPException(500, "Yandex Delivery token not configured")
    payload = {
        "type": "pickup_point",
        "is_yandex_branded": True,
        "is_post_office": True,
        "is_not_branded_partner_station": True,
        "payment_methods": ["already_paid", "card_on_receipt"],
    }
    if "geo_id" in req and req["geo_id"] is not None: payload["geo_id"] = int(req["geo_id"])

    elif (
            isinstance(req.get("latitude"), dict)
            and isinstance(req.get("longitude"), dict)
            and "from" in req["latitude"]
            and "from" in req["longitude"]
    ):
        payload["latitude"] = req["latitude"]
        payload["longitude"] = req["longitude"]

    elif "latitude" in req and "longitude" in req:
        lat = float(req["latitude"])
        lon = float(req["longitude"])
        radius = int(req.get("radius", 10000))
        radius = max(100, min(40000, radius))                     
        km = radius / 1000
        dlat = km / 111.0
        dlon = km / (111.32 * max(0.1, abs(__import__("math").cos(lat * 3.1416 / 180))))

        payload["latitude"] = {"from": lat - dlat, "to": lat + dlat}
        payload["longitude"] = {"from": lon - dlon, "to": lon + dlon}

    else: raise HTTPException(400, "Provide geo_id or latitude/longitude (+optional radius)")

    headers = {
        "Authorization": f"Bearer {YANDEX_DELIVERY_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"{YANDEX_DELIVERY_BASE_URL}/api/b2b/platform/pickup-points/list"

    timeout = httpx.Timeout(connect=5, read=20, write=10, pool=5)
    async with httpx.AsyncClient(timeout=timeout) as client: resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code != 200: raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()

@yandex_router.get("/get-pvz-all")
async def get_pvz_all():
    """
    Load all PVZ for Russia + Kazakhstan (merged cache or direct Yandex call).
    This endpoint should respond with:
        { "points": [ ... ] }
    """
    if not YANDEX_DELIVERY_TOKEN: raise HTTPException(500, "Token missing")
    payload = {
        "type": "pickup_point",
        "is_not_branded_partner_station": True,
    }

    headers = {
        "Authorization": f"Bearer {YANDEX_DELIVERY_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"{YANDEX_DELIVERY_BASE_URL}/api/b2b/platform/pickup-points/list"
    async with httpx.AsyncClient(timeout=60) as client: resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code != 200: raise HTTPException(resp.status_code, resp.text)
    return resp.json()

@yandex_router.post("/availability")
async def yandex_availability(req: AvailabilityRequest):
    if req.delivery_mode == "self_pickup":
        pid = req.destination.platform_station_id
        if not pid: raise HTTPException(422, detail="destination.platform_station_id is required for self_pickup")
        destination_node = {
            "type": "platform_station",
            "platform_station": {"platform_id": str(pid)},
        }
        last_mile_policy = "self_pickup"
    else:
        addr = req.destination.full_address
        if not addr: raise HTTPException(422, detail="destination.full_address is required for time_interval")
        destination_node = {
            "type": "custom_location",
            "custom_location": {"details": {"full_address": str(addr)}},
        }
        if req.destination.latitude is not None and req.destination.longitude is not None:
            destination_node["custom_location"]["latitude"] = float(req.destination.latitude)
            destination_node["custom_location"]["longitude"] = float(req.destination.longitude)

        last_mile_policy = "time_interval"

    operator_request_id = f"avail-{int(time.time())}"
    request_id = operator_request_id
    body = {
        "info": {"operator_request_id": operator_request_id, "comment": "availability-check"},
        "source": {"platform_station": {"platform_id": str(YANDEX_DELIVERY_WAREHOUSE_ID)}},
        "destination": destination_node,
        "items": [
            {
                "count": 1,
                "name": "Availability check",
                "article": "AVAIL-TEST",
                "billing_details": {"unit_price": 100, "assessed_unit_price": 100, "nds": -1},
                "physical_dims": {"dx": 25, "dy": 15, "dz": 10},
                "place_barcode": "box-1",
            }
        ],
        "places": [
            {
                "barcode": "box-1",
                "description": "Stub box",
                "physical_dims": {"dx": 25, "dy": 15, "dz": 10, "weight_gross": 100},
            }
        ],
        "billing_info": {"payment_method": "already_paid"},
        "recipient_info": {
            "first_name": "Получатель",
            "last_name": "",
            "phone": "+79990000000",
            "email": "no-reply@example.com",
        },
        "last_mile_policy": last_mile_policy,
        "particular_items_refuse": False,
        "forbid_unboxing": False,
    }

    url = f"{YANDEX_DELIVERY_BASE_URL}/api/b2b/platform/offers/create"
    headers = {
        "Authorization": f"Bearer {YANDEX_DELIVERY_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Language": "ru",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            url,
            params={"send_unix": bool(req.send_unix), "request_id": request_id},
            json=body,
            headers=headers,
        )
        if r.status_code >= 400:
            logger.warning("Yandex availability request failed with status %s", r.status_code)
            try: raise HTTPException(status_code=400, detail=r.json())
            except Exception: raise HTTPException(status_code=400, detail={"message": r.text})

        data = r.json()
    offers = data.get("offers") or []

    slim = []
    nearest = None
    nearest_min = None
    nearest_price_str = None

    for o in offers:
        det = o.get("offer_details") or {}
        di = det.get("delivery_interval") or {}
        offer_id = o.get("offer_id")
        expires_at = o.get("expires_at")
        station_id = o.get("station_id")
        di_min = di.get("min")
        di_max = di.get("max")
        di_policy = di.get("policy")
        price_str = det.get("pricing_total") or det.get("pricing")
        item = {
            "offer_id": offer_id,
            "expires_at": expires_at,
            "pricing_total": price_str,
            "station_id": station_id,
            "interval": {"from": di_min, "to": di_max, "policy": di_policy},
        }
        slim.append(item)

        if di_min is not None:
            try: di_min_int = int(di_min)
            except Exception: di_min_int = None

            if di_min_int is not None and (nearest_min is None or di_min_int < nearest_min):
                nearest_min = di_min_int
                nearest = item
                nearest_price_str = price_str

    nearest_price_rub = None
    if nearest_price_str is not None:
        s = str(nearest_price_str).strip()
        m = re.search(r"(\d+(?:[.,]\d+)?)", s)
        if m:
            try: nearest_price_rub = int(round(float(m.group(1).replace(",", "."))))
            except Exception: nearest_price_rub = None

    deliverable = len(offers) > 0

    return {
        "ok": True,
        "deliverable": deliverable,
        "offers_count": len(offers),
        "nearest": {
            "offer_id": nearest.get("offer_id") if nearest else None,
            "pricing_total": nearest.get("pricing_total") if nearest else None,
            "price_rub": nearest_price_rub,
            "interval": nearest.get("interval") if nearest else None,
            "expires_at": nearest.get("expires_at") if nearest else None,
            "station_id": nearest.get("station_id") if nearest else None,
        },
        "offers": slim,
    }
