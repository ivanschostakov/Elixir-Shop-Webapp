import os
import logging
import pathlib

from urllib.parse import quote_plus, urlsplit
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from starlette.templating import Jinja2Templates

def env(name: str, default: str | None = None, *, strip: bool = True) -> str | None:
    v = os.getenv(name, default)
    if v is None: return None
    return v.strip() if strip else v

def env_int(name: str, default: int | None = None) -> int | None:
    v = env(name)
    if v is None or v == "": return default
    try: return int(v)
    except ValueError: return default

def env_bool(name: str, default: bool = False) -> bool:
    v = env(name)
    if v is None or v == "": return default
    return v.strip().lower() in {"1", "true", "yes", "on"}

def env_list_ints(name: str) -> list[int]:
    raw = env(name, "")
    if not raw: return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try: out.append(int(p))
        except ValueError: pass

    return out

def build_sync_dsn(user: str, password: str, host: str, port: int, db: str) -> str: return f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(db)}"
def build_async_dsn(user: str, password: str, host: str, port: int, db: str) -> str: return f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(db)}"

def normalize_yandex_delivery_base_url(raw: str | None) -> str:
    """
    Normalize base URL for Yandex "other-day" platform endpoints.
    Production platform API lives on b2b-authproxy host.
    """
    source = (raw or "").strip().strip("'\"")
    if not source:
        return "https://b2b-authproxy.taxi.yandex.net"

    parsed = urlsplit(source if "://" in source else f"https://{source}")
    host = parsed.netloc.strip().lower()
    if not host:
        return source.rstrip("/")

    if host == "b2b.taxi.yandex.net":
        host = "b2b-authproxy.taxi.yandex.net"

    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}"

load_dotenv()
UFA_TZ = ZoneInfo("Asia/Yekaterinburg")

OWNER_TG_IDS      = env_list_ints("OWNER_TG_IDS")
ADMIN_TG_IDS      = env_list_ints("ADMIN_TG_IDS")
TELETHON_PHONE    = env("TELETHON_PHONE", "")
TELETHON_API_ID   = env("TELETHON_API_ID", "")
TELETHON_API_HASH = env("TELETHON_API_HASH", "")
TELETHON_PASSWORD = env("TELETHON_PASSWORD", None)

ADMIN_PANEL_TOKEN = env("ADMIN_PANEL_TOKEN", "")
ELIXIR_CHAT_ID = env_int("ELIXIR_CHAT_ID", 0)

PROFESSOR_BOT_TOKEN  = env("PROFESSOR_BOT_TOKEN", "")
DOSE_BOT_TOKEN = env("DOSE_BOT_TOKEN", "")
NEW_BOT_TOKEN = env("NEW_BOT_TOKEN", "")

PROFESSOR_ASSISTANT_ID  = env("PROFESSOR_ASSISTANT_ID", "")
DOSE_ASSISTANT_ID = env("DOSE_ASSISTANT_ID", "")
NEW_ASSISTANT_ID = env("NEW_ASSISTANT_ID", "")

PROFESSOR_OPENAI_API  = env("PROFESSOR_OPENAI_API", "")
DOSE_OPENAI_API = env("DOSE_OPENAI_API", "")
NEW_OPENAI_API = env("NEW_OPENAI_API", "")

POSTGRES_DB       = env("POSTGRES_DB", "postgres") or "postgres"
POSTGRES_USER     = env("POSTGRES_USER", "postgres") or "postgres"
POSTGRES_HOST     = env("POSTGRES_HOST", "localhost") or "localhost"
POSTGRES_PORT     = env_int("POSTGRES_PORT", 5432) or 5432
POSTGRES_PASSWORD = env("POSTGRES_PASSWORD", "") or ""

SYNC_DATABASE_URL  = build_sync_dsn(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB)
ASYNC_DATABASE_URL = build_async_dsn(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB)

BASE_DIR = pathlib.Path(__file__).resolve().parent
WORKING_DIR = BASE_DIR

SRC_DIR       = BASE_DIR / "src"
DATA_DIR      = BASE_DIR / "data"
LOGS_DIR      = BASE_DIR / "logs"
IMAGES_DIR    = SRC_DIR / "webapp" / "static" / "images"
DOWNLOADS_DIR = DATA_DIR / "downloads"
TEMPLATES_DIR = BASE_DIR / "src" / "webapp" / "templates"

API_PREFIX = "/api/v1"

for d in (DATA_DIR, DOWNLOADS_DIR): d.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

ENTERPRISE_URL      = env("ENTERPRISE_URL", "")
ENTERPRISE_LOGIN    = env("ENTERPRISE_LOGIN", "")
ENTERPRISE_PASSWORD = env("ENTERPRISE_PASSWORD", "")
MOY_SKLAD_BASE_URL = env("MOY_SKLAD_BASE_URL", "https://api.moysklad.ru/api/remap/1.2") or "https://api.moysklad.ru/api/remap/1.2"
MOY_SKLAD_TOKEN = env("MOY_SKLAD_TOKEN", "")
MOY_SKLAD_TIMEOUT_SECONDS = env_int("MOY_SKLAD_TIMEOUT_SECONDS", 30) or 30
MOY_SKLAD_STOCK_RESERVE = env_int("MOY_SKLAD_STOCK_RESERVE", 3) or 3
MOY_SKLAD_SYNC_INTERVAL_SECONDS = env_int("MOY_SKLAD_SYNC_INTERVAL_SECONDS", 900) or 900
MOY_SKLAD_ORDER_SYNC_ENABLED = env_bool("MOY_SKLAD_ORDER_SYNC_ENABLED", False)
MOY_SKLAD_ORGANIZATION_ID = env("MOY_SKLAD_ORGANIZATION_ID", "")
MOY_SKLAD_SALES_CHANNEL_HREF = env("MOY_SKLAD_SALES_CHANNEL_HREF", "")
MOY_SKLAD_COUNTERPARTY_EXTERNAL_CODE_PREFIX = env("MOY_SKLAD_COUNTERPARTY_EXTERNAL_CODE_PREFIX", "app_user") or "app_user"
MOY_SKLAD_CUSTOMERORDER_EXTERNAL_CODE_PREFIX = env("MOY_SKLAD_CUSTOMERORDER_EXTERNAL_CODE_PREFIX", "app_order") or "app_order"

CDEK_ACCOUNT         = env("CDEK_ACCOUNT", "")
CDEK_API_URL         = env("CDEK_API_URL", "")
CDEK_SECURE_PASSWORD = env("CDEK_SECURE_PASSWORD", "")

CDEK_SENDER_CITY         = "Уфа"
CDEK_SENDER_ADDRESS      = "ул. Революционная, 98/1 блок А"
CDEK_SENDER_CITY_CODE    = 256
CDEK_SENDER_POSTAL_CODE  = "450078"
CDEK_SENDER_COUNTRY_CODE = "RU"

CDEK_SENDER_NAME  = "ИП Хоменко Татьяна Ивановна"
CDEK_SENDER_PHONE = "+79610387977"
CDEK_SENDER_EMAIL = "shop@example.com"

YANDEX_MAP_TOKEN                  = env("YANDEX_MAP_TOKEN", "")
YANDEX_WAREHOUSE_LON              = float(env("YANDEX_WAREHOUSE_LON", "54.731721"))
YANDEX_WAREHOUSE_LAT              = float(env("YANDEX_WAREHOUSE_LAT", "55.974349"))
YANDEX_GEOCODER_TOKEN             = env("YANDEX_GEOCODER_TOKEN", "")
GEOSUGGEST_API_URL                = env("GEOSUGGEST_API_URL", "")
GEOSUGGEST_API_KEY                = env("GEOSUGGEST_API_KEY", "")
GEOCODE_API_URL                   = env("GEOCODE_API_URL", "https://geocode-maps.yandex.ru/v1/") or "https://geocode-maps.yandex.ru/v1/"
GEOCODE_API_KEY                   = env("GEOCODE_API_KEY", YANDEX_GEOCODER_TOKEN or "") or (YANDEX_GEOCODER_TOKEN or "")
YANDEX_DELIVERY_TOKEN             = env("YANDEX_DELIVERY_TOKEN", "")
YANDEX_DELIVERY_BASE_URL          = normalize_yandex_delivery_base_url(env("YANDEX_DELIVERY_BASE_URL", ""))
YANDEX_DELIVERY_WAREHOUSE_ID      = env("YANDEX_DELIVERY_WAREHOUSE_ID", "")
YANDEX_WAREHOUSE_ADDRESS_FULLNAME = env("YANDEX_WAREHOUSE_ADDRESS_FULLNAME", "")

YANDEX_DISK_OAUTH_TOKEN = env("YANDEX_DISK_OAUTH_TOKEN", "")
AMOCRM_CLIENT_ID      = env("AMOCRM_CLIENT_ID", "")
AMOCRM_AUTH_CODE      = env("AMOCRM_AUTH_CODE", "")
AMOCRM_LOGIN_EMAIL    = env("AMOCRM_LOGIN_EMAIL", "")
AMOCRM_BASE_DOMAIN    = env("AMOCRM_BASE_DOMAIN", "")
AMOCRM_REDIRECT_URI   = env("AMOCRM_REDIRECT_URI", "")
AMOCRM_ACCESS_TOKEN   = env("AMOCRM_ACCESS_TOKEN", "")
AMOCRM_CLIENT_SECRET  = env("AMOCRM_CLIENT_SECRET", "")
AMOCRM_REFRESH_TOKEN  = env("AMOCRM_REFRESH_TOKEN", "")
AMOCRM_LOGIN_PASSWORD = env("AMOCRM_LOGIN_PASSWORD", "")

_log = logging.getLogger("config")

if not OWNER_TG_IDS: _log.warning("ADMIN_TG_IDS is empty or invalid; admin-only filters may not work.")
if not PROFESSOR_BOT_TOKEN: _log.warning("AI_BOT_TOKEN is empty.")

SMTP_USER          = env("SMTP_USER", "")
SMTP_PASSWORD      = env("SMTP_PASSWORD", "")
WEBAPP_BASE_DOMAIN = env("WEBAPP_BASE_DOMAIN", "")
INTERNAL_API_TOKEN = env("INTERNAL_API_TOKEN", "")
INTELLECTMONEY_API_BASE = env("INTELLECTMONEY_API_BASE", "https://api.intellectmoney.ru") or "https://api.intellectmoney.ru"
INTELLECTMONEY_SHOP_ID = env_int("INTELLECTMONEY_SHOP_ID", None)
INTELLECTMONEY_BEARER_TOKEN = env("INTELLECTMONEY_BEARER_TOKEN", "")
INTELLECTMONEY_SIGN_SECRET_KEY = env("INTELLECTMONEY_SIGN_SECRET_KEY", "")
INTELLECTMONEY_SECRET_KEY = env("INTELLECTMONEY_SECRET_KEY", "")
