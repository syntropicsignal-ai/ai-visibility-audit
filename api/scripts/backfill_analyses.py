"""Backfill missing (response, brand) Analysis rows.

PYTHONPATH=. uv run python scripts/backfill_analyses.py [--run-id N]
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
    p.add_argument("--run-id", type=int, default=None, help="Backfill a single run")
    p.add_argument("--dry-run", action="store_true", help="Count missing pairs without writing")
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-analyze ALL responses (not just missing). Use after changing detection logic.",
    )
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()

    here = Path(__file__).resolve().parent
    api_root = here.parent
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from sqlalchemy import select

    from app.database import async_session
    from app.models import Analysis, Brand, Response
    from app.services.analysis import analyze_response

    async with async_session() as db:
        brands = list((await db.execute(select(Brand))).scalars().all())
        brand_ids = {b.id for b in brands}

        # Load responses in scope
        q = select(Response)
        if args.run_id is not None:
            q = q.where(Response.run_id == args.run_id)
        responses = list((await db.execute(q)).scalars().all())
        logger.info("Loaded %d responses, %d brands", len(responses), len(brands))

        # Find which (response_id, brand_id) pairs already have Analysis rows
        existing_q = select(Analysis.response_id, Analysis.brand_id)
        if args.run_id is not None:
            existing_q = existing_q.join(Response).where(Response.run_id == args.run_id)
        existing_pairs: set[tuple[int, int]] = set()
        for row in (await db.execute(existing_q)).all():
            existing_pairs.add((row[0], row[1]))

        # Find responses that need backfill
        to_backfill: list[Response] = []
        if args.force:
            # Re-analyze every response (e.g. after fixing detection logic)
            to_backfill = list(responses)
        else:
            # Only responses missing analyses for some brands
            for resp in responses:
                missing = brand_ids - {bid for rid, bid in existing_pairs if rid == resp.id}
                if missing:
                    to_backfill.append(resp)

        logger.info(
            "%d responses need backfill (out of %d)",
            len(to_backfill),
            len(responses),
        )

        if args.dry_run:
            logger.info("Dry run — exiting without writing")
            return 0

        if not to_backfill:
            logger.info("Nothing to backfill")
            return 0

        # For each response, delete any existing analyses and re-run the
        # full analysis pipeline. This is simpler than trying to add only
        # the missing brands, because the position ranking depends on ALL
        # brands in the response (rank = order of first mention across all
        # brands). Re-running with all brands gives correct ranks.
        created = 0
        for i, resp in enumerate(to_backfill, 1):
            if not resp.text:
                continue
            # Delete existing analyses for this response so we can re-run
            existing_analyses = list(
                (await db.execute(select(Analysis).where(Analysis.response_id == resp.id)))
                .scalars()
                .all()
            )
            for a in existing_analyses:
                await db.delete(a)
            await db.flush()

            new_analyses = await analyze_response(db, resp, brands)
            created += len(new_analyses)
            if i % 10 == 0 or i == len(to_backfill):
                logger.info(
                    "  [%d/%d] response %d → %d analyses",
                    i,
                    len(to_backfill),
                    resp.id,
                    len(new_analyses),
                )

        logger.info("Created %d analysis rows total", created)
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
