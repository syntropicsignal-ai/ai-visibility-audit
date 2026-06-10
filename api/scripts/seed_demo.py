"""Seed / clear / inspect the demo dataset.

PYTHONPATH=. uv run python scripts/seed_demo.py [--clear|--status]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--clear", action="store_true", help="Wipe the demo dataset")
    g.add_argument("--status", action="store_true", help="Print demo status and exit")
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()

    here = Path(__file__).resolve().parent
    api_root = here.parent
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from app.database import async_session
    from app.services.demo_seed import clear_demo, demo_status, seed_demo

    async with async_session() as db:
        if args.status:
            logger.info("demo status: %s", await demo_status(db))
            return 0
        if args.clear:
            try:
                result = await clear_demo(db)
            except ValueError as e:
                logger.error("%s", e)
                return 1
            logger.info("clear: %s", result)
            return 0
        try:
            summary = await seed_demo(db)
        except ValueError as e:
            logger.error("%s", e)
            return 1
        logger.info(
            "seeded demo: %d brands, %d prompts, %d runs, %d responses, %d analyses",
            summary.brands,
            summary.prompts,
            summary.runs,
            summary.responses,
            summary.analyses,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
