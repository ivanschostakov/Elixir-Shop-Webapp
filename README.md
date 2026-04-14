# Shop

## Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

## Config
- Fill `.env` from `.env.example`.
- Static frontend files are in `src/webapp/static`.
- DB migrations are under `migrations/` with `alembic.ini`.
- Also includes merged packages from `misc`: `src/admin_panel` and `src/onec`.
