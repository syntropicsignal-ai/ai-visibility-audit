import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.config import settings
from app.logging_config import configure_logging

configure_logging()

# Overlay must patch settings before route/provider modules import them.
from app.runtime_config import apply_runtime_config, load_runtime_config  # noqa: E402

apply_runtime_config(load_runtime_config())

from app.database import async_session  # noqa: E402
from app.models import Run, RunStatus  # noqa: E402
from app.routes import (  # noqa: E402
    analytics,
    brands,
    config as config_route,
    demo,
    generator,
    prompts,
    report,
    runs,
    schedule,
    sources,
)
from app.services.scheduler import scheduler_loop  # noqa: E402

import logging  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session() as db:
        result = await db.execute(
            update(Run)
            .where(Run.status == RunStatus.running)
            .values(status=RunStatus.failed)
            .returning(Run.id)
        )
        orphan_ids = [row[0] for row in result.all()]
        if orphan_ids:
            await db.commit()
            logger.warning(
                "Marked %d orphan run(s) as failed on startup: %s "
                "(asyncio tasks did not survive last shutdown)",
                len(orphan_ids),
                orphan_ids,
            )
        else:
            await db.rollback()
            logger.info("No orphan runs to clean up on startup")

    scheduler_task = asyncio.create_task(scheduler_loop(), name="scheduler-loop")

    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="AI Visibility Audit API",
    description="Track brand visibility across AI assistants",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
app.include_router(runs.router, prefix="/api/v1/runs", tags=["runs"])
app.include_router(brands.router, prefix="/api/v1/brands", tags=["brands"])
app.include_router(sources.router, prefix="/api/v1/sources", tags=["sources"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(report.router, prefix="/api/v1/report", tags=["report"])
app.include_router(schedule.router, prefix="/api/v1/schedule", tags=["schedule"])
app.include_router(generator.router, prefix="/api/v1/generator", tags=["generator"])
app.include_router(config_route.router, prefix="/api/v1/config", tags=["config"])
app.include_router(demo.router, prefix="/api/v1/demo", tags=["demo"])


@app.get("/health")
async def health():
    return {"status": "ok"}
