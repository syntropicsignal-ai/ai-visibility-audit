"""In-process scheduler: ticks every minute, triggers runs for
enabled schedules whose interval has elapsed. No catch-up across
long downtimes — runs at most one missed job per tick."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import async_session
from app.models import RunSchedule


logger = logging.getLogger(__name__)


# Tick interval — how often the scheduler checks for due schedules.
# 60s is plenty for hour-granular schedules and keeps DB load trivial.
TICK_SECONDS = 60


async def _process_due_schedules() -> None:
    async with async_session() as db:
        rows = list(
            (await db.execute(select(RunSchedule).where(RunSchedule.enabled.is_(True))))
            .scalars()
            .all()
        )
        if not rows:
            return

        now = datetime.now(timezone.utc)
        due: list[RunSchedule] = []
        for s in rows:
            if s.last_triggered_at is None:
                due.append(s)
                continue
            elapsed = now - s.last_triggered_at
            if elapsed >= timedelta(hours=s.interval_hours):
                due.append(s)

        for s in due:
            # Mark triggered *before* execution so a long-running pipeline
            # that overlaps the next tick won't double-trigger.
            s.last_triggered_at = now
        if due:
            await db.commit()

    # Trigger runs *after* the commit so any DB hiccup during execution
    # doesn't leave the schedule row half-updated. Imported lazily to
    # avoid a top-level import loop with run_service → analytics →
    # services package init.
    from app.services.run_service import execute_run

    for s in due:
        try:
            async with async_session() as db:
                await execute_run(db, brand_id=s.brand_id)
            logger.info(
                "Scheduled run completed for brand_id=%s (schedule_id=%s)",
                s.brand_id,
                s.id,
            )
        except Exception:  # noqa: BLE001 — log and keep the loop alive
            logger.exception(
                "Scheduled run failed for brand_id=%s (schedule_id=%s)",
                s.brand_id,
                s.id,
            )


async def scheduler_loop() -> None:
    """Run-once-per-process loop. Cancel by cancelling the task."""
    logger.info("Scheduler loop started (tick=%ds)", TICK_SECONDS)
    while True:
        try:
            await _process_due_schedules()
        except Exception:  # noqa: BLE001 — never let the loop die
            logger.exception("Scheduler tick raised; continuing")
        await asyncio.sleep(TICK_SECONDS)
