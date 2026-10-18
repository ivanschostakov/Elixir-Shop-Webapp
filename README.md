# Elixir Shop Webapp

Python web application and integration service for the Elixir Peptide commerce ecosystem. It combines the customer-facing web experience, internal bot APIs, catalog and cart persistence, fulfillment services, and operational workers.

## Related Repositories

- [Shop Application](https://github.com/ivanschostakov/Elixir-Shop-Application): the React Native customer application, its backend, and web administration interface.
- [AI Bot Suite](https://github.com/ivanschostakov/Elixir-AI-Bot): Telegram AI assistants that integrate with configured shop APIs.

This repository contains the web application and integration service; mobile application source is maintained separately.

## Highlights

- Product catalog, search, favorites, carts, promo codes, and checkout routes.
- Internal APIs for AI assistants and Telegram workflows.
- PostgreSQL persistence with SQLAlchemy and Alembic.
- MoySklad inventory and order synchronization.
- 1C, amoCRM, CDEK, Yandex, and payment integrations.
- Telegram administration bot and long-running worker supervision.

## Architecture

- `src/webapp/`: web routes, schemas, templates, and static assets.
- `src/internal_api/`: authenticated bot-to-shop operations.
- `src/database/`: models, schemas, and CRUD operations.
- `src/moysklad/`: catalog relinking and order synchronization.
- `src/services/`: delivery, payments, geocoding, and fulfillment.
- `src/admin_panel/`: Telegram-based operational administration.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python run.py
```

Static frontend files are stored in `src/webapp/static`. Database migrations are under `migrations/` and configured through `alembic.ini`.

## MoySklad Initial Relink

Preview changes without modifying the database or images:

```bash
python -m src.moysklad.initial_relink --dry-run
```

Apply the relink operation:

```bash
python -m src.moysklad.initial_relink
```

The apply operation updates identifiers and renames images with a backup. Review the dry-run output first.

## Security

- Never commit `.env`, Telethon sessions, CRM credentials, database exports, user data, or logs.
- Use scoped development credentials for external integrations.
- Rotate any credential that has previously appeared in Git history.
