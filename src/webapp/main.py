import logging

from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from uvicorn import Server, Config

from config import BASE_DIR, templates, API_PREFIX
from src.webapp.routes import *

logger = logging.getLogger("webapp.uvicorn")
app = FastAPI(title="ElixirPeptides")
app.mount("/static", StaticFiles(directory=BASE_DIR / "src" / "webapp" / "static", html=True), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "https://www.devsivanschostakov.org", "https://www.devsivanschostakov.org", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(product_router, prefix=API_PREFIX)
app.include_router(search_router, prefix=API_PREFIX)
app.include_router(cart_router, prefix=API_PREFIX)
app.include_router(cdek_router, prefix=API_PREFIX)
app.include_router(yandex_router, prefix=API_PREFIX)
app.include_router(payments_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(favourite_router, prefix=API_PREFIX)
app.include_router(categories_router, prefix=API_PREFIX)
app.include_router(promo_codes_router, prefix=API_PREFIX)
app.include_router(internal_bot_router, prefix=API_PREFIX)
app.include_router(internal_users_router, prefix=API_PREFIX)
app.include_router(internal_usage_router, prefix=API_PREFIX)
app.include_router(internal_catalog_router, prefix=API_PREFIX)
app.include_router(internal_carts_router, prefix=API_PREFIX)
app.include_router(internal_orders_router, prefix=API_PREFIX)
app.include_router(internal_reports_router, prefix=API_PREFIX)
app.include_router(webhooks_router)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )

@app.get("/product/{path:path}", response_class=HTMLResponse)
async def spa_product(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )

async def run_app():
    logger.info("Starting uvicorn server (reload=%s)", False)
    server = Server(Config(app, reload=False, log_config=None))
    await server.serve()
    logger.warning("uvicorn server stopped")
