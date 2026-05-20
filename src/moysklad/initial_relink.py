import argparse
import asyncio
import json

from src.logger import setup_logging
from src.moysklad.relink import run_moysklad_initial_relink


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Relink local 1C IDs to MoySklad IDs for products/features in Shop-Webapp."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print relink plan without changing DB or images.",
    )
    args = parser.parse_args()

    stats = await run_moysklad_initial_relink(dry_run=args.dry_run)
    print(json.dumps(stats.as_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    setup_logging()
    asyncio.run(_main())
