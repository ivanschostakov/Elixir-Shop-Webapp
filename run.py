import asyncio
import logging
import signal
import time

from src.webapp.main import run_app
from src.logger import setup_logging
from src.onec.main import OneCEnterprise
from src.admin_panel.bot.main import run_admin_bot
from src.services.yandex import promo_codes_worker
from src.services.cdek import client as cdek_client

logger = logging.getLogger(__name__)
RESTART_DELAY_SECONDS = 3.0
HEARTBEAT_SECONDS = 60.0


async def _run_forever(name: str, runner):
    while True:
        try:
            logger.info("Starting %s", name)
            await runner()
            logger.warning("%s returned unexpectedly. Restarting in %.1fs", name, RESTART_DELAY_SECONDS)
        except asyncio.CancelledError:
            logger.info("%s cancelled", name)
            raise
        except Exception:
            logger.exception("%s crashed. Restarting in %.1fs", name, RESTART_DELAY_SECONDS)
        await asyncio.sleep(RESTART_DELAY_SECONDS)


def _task_state(task: asyncio.Task) -> str:
    if not task.done(): return "alive"
    if task.cancelled(): return "cancelled"
    try: exc = task.exception()
    except asyncio.CancelledError: return "cancelled"
    if exc is None: return "done:ok"
    return f"done:exc={type(exc).__name__}"


async def _heartbeat(stop_event: asyncio.Event, task_map: dict[str, asyncio.Task]):
    next_tick = time.monotonic() + HEARTBEAT_SECONDS
    while not stop_event.is_set():
        snapshot = ", ".join(f"{name}={_task_state(task)}" for name, task in task_map.items())
        active_tasks_count = len(asyncio.all_tasks())
        loop_lag_ms = max(0, int((time.monotonic() - next_tick) * 1000))
        logger.info("Heartbeat | active_tasks=%d | loop_lag_ms=%d | tasks=[%s]", active_tasks_count, loop_lag_ms, snapshot)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            pass
        next_tick += HEARTBEAT_SECONDS


async def main():
    stop_event = asyncio.Event()
    onec = OneCEnterprise()
    task_map: dict[str, asyncio.Task] = {
        "onec.postgres_worker": asyncio.create_task(_run_forever("onec.postgres_worker", onec.postgres_worker)),
        "admin_bot": asyncio.create_task(_run_forever("admin_bot", run_admin_bot)),
        "webapp": asyncio.create_task(_run_forever("webapp", run_app)),
        "promo_codes_worker": asyncio.create_task(_run_forever("promo_codes_worker", promo_codes_worker)),
        "cdek.token_worker": asyncio.create_task(_run_forever("cdek.token_worker", cdek_client.token_worker)),
    }
    task_map["heartbeat"] = asyncio.create_task(_heartbeat(stop_event, task_map))
    tasks = list(task_map.values())

    async def shutdown():
        if stop_event.is_set(): return
        stop_event.set()
        logger.warning("Shutting down gracefully...")
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try: await onec.close()
        except Exception: logger.exception("Failed to close OneC client cleanly")
        logger.info("All background tasks stopped cleanly.")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown()))

    try: await asyncio.gather(*tasks)
    except asyncio.CancelledError: logger.info("Tasks cancelled; exiting gracefully.")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        await shutdown()

if __name__ == "__main__":
    setup_logging()
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.warning("Interrupted manually (Ctrl+C). Exiting.")
