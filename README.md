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

## MoySklad Initial Relink
- Dry run (no DB/image changes): `python -m src.moysklad.initial_relink --dry-run`
- Apply relink (updates DB IDs + renames images with backup): `python -m src.moysklad.initial_relink`
