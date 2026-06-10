"""Staged progress observability for the prompt pipeline. NoopTracker
is the drop-in for CLI smokes / tests."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PipelineRun

logger = logging.getLogger(__name__)


@dataclass
class StageEvent:
    stage: str
    started_at: str
    completed_at: str | None = None
    status: str = "running"  # running | completed | failed | skipped
    summary: str = ""
    details: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "summary": self.summary,
            "details": self.details,
            "warnings": self.warnings,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineTracker:
    # Serializes DB writes through an asyncio.Lock — parallel stages
    # in a gather block would otherwise race on the JSONB column.

    def __init__(self, db: AsyncSession, run_id: int):
        self.db = db
        self.run_id = run_id
        self._stages: list[StageEvent] = []
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls, db: AsyncSession, domain: str) -> PipelineTracker:
        row = PipelineRun(domain=domain, status="running", stages=[])
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return cls(db, row.id)

    async def _flush(self) -> None:
        await self.db.execute(
            update(PipelineRun)
            .where(PipelineRun.id == self.run_id)
            .values(stages=[s.to_dict() for s in self._stages])
        )
        await self.db.commit()

    async def start(self, stage: str, summary: str = "") -> StageEvent:
        async with self._lock:
            ev = StageEvent(
                stage=stage,
                started_at=_now_iso(),
                status="running",
                summary=summary,
            )
            self._stages.append(ev)
            await self._flush()
            return ev

    async def complete(
        self,
        ev: StageEvent,
        *,
        summary: str | None = None,
        details: dict | None = None,
        warnings: list[str] | None = None,
        status: str = "completed",
    ) -> None:
        async with self._lock:
            ev.completed_at = _now_iso()
            ev.status = status
            if summary is not None:
                ev.summary = summary
            if details is not None:
                ev.details = details
            if warnings is not None:
                ev.warnings = warnings
            await self._flush()

    async def fail(self, ev: StageEvent, error: str) -> None:
        await self.complete(ev, status="failed", summary=f"FAILED: {error}")

    async def finalize(
        self,
        *,
        generator_run_id: int | None = None,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            await self.db.execute(
                update(PipelineRun)
                .where(PipelineRun.id == self.run_id)
                .values(
                    status="failed" if error else "completed",
                    completed_at=datetime.now(timezone.utc),
                    error=error,
                    generator_run_id=generator_run_id,
                )
            )
            await self.db.commit()

    @asynccontextmanager
    async def stage(self, name: str, summary: str = ""):
        """Context manager for a stage — auto-fails on exception, completes
        on clean exit. The body sets `event.summary`, `event.details`,
        `event.warnings` directly to record what happened.

        Usage:
            async with tracker.stage("stage_2.corpus") as ev:
                corpus = await build_category_corpus(...)
                ev.summary = f"WildChat={n_wc} PAA={n_paa} suggestions={n_sugg}"
                ev.details = {"counts": corpus.counts}
                ev.warnings = corpus.warnings
        """
        ev = await self.start(name, summary)
        try:
            yield ev
        except Exception as e:
            await self.fail(ev, str(e))
            raise
        else:
            await self.complete(ev)


class NoopTracker:
    """Drop-in replacement for callers that don't need live progress.

    Same API surface as `PipelineTracker`, but every method is a noop.
    Lets `generate_prompt_set` accept `tracker: PipelineTracker | NoopTracker`
    without runtime checks — CLI smokes and tests pass NoopTracker; the
    long-running run endpoint passes a real tracker.
    """

    async def start(self, stage: str, summary: str = "") -> StageEvent:
        return StageEvent(stage=stage, started_at=_now_iso())

    async def complete(self, ev: StageEvent, **kwargs: Any) -> None:
        return

    async def fail(self, ev: StageEvent, error: str) -> None:
        return

    async def finalize(self, **kwargs: Any) -> None:
        return

    @asynccontextmanager
    async def stage(self, name: str, summary: str = ""):
        ev = await self.start(name, summary)
        try:
            yield ev
        except Exception:
            raise
