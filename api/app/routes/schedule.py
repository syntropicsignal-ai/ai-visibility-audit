"""Schedule endpoints.

Read / update the run schedule for the self brand. Operates on the
single self-brand row — for multi-brand workspaces this would need a
brand_id selector, but the OSS surface is single-self-brand by
construction.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Brand, RunSchedule
from app.schemas import RunScheduleOut, RunScheduleUpdate


router = APIRouter()


def _to_out(s: RunSchedule) -> RunScheduleOut:
    next_run_at = None
    if s.enabled and s.last_triggered_at is not None:
        next_run_at = s.last_triggered_at + timedelta(hours=s.interval_hours)
    return RunScheduleOut(
        brand_id=s.brand_id,
        enabled=s.enabled,
        interval_hours=s.interval_hours,
        last_triggered_at=s.last_triggered_at,
        next_run_at=next_run_at,
    )


async def _self_brand(db: AsyncSession) -> Brand:
    brand = (
        await db.execute(select(Brand).where(Brand.is_self.is_(True)).limit(1))
    ).scalar_one_or_none()
    if brand is None:
        raise HTTPException(
            status_code=400,
            detail="No self-brand configured. Mark a brand as is_self=True before "
            "configuring a schedule.",
        )
    return brand


async def _get_or_create(db: AsyncSession, brand_id: int) -> RunSchedule:
    row = (
        await db.execute(select(RunSchedule).where(RunSchedule.brand_id == brand_id))
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = RunSchedule(brand_id=brand_id, enabled=False, interval_hours=168)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("", response_model=RunScheduleOut)
async def get_schedule(db: AsyncSession = Depends(get_db)) -> RunScheduleOut:
    brand = await _self_brand(db)
    row = await _get_or_create(db, brand.id)
    return _to_out(row)


@router.put("", response_model=RunScheduleOut)
async def update_schedule(
    body: RunScheduleUpdate,
    db: AsyncSession = Depends(get_db),
) -> RunScheduleOut:
    brand = await _self_brand(db)
    row = await _get_or_create(db, brand.id)

    if body.enabled is not None:
        row.enabled = body.enabled
    if body.interval_hours is not None:
        if body.interval_hours < 1:
            raise HTTPException(
                status_code=400,
                detail="interval_hours must be ≥ 1",
            )
        row.interval_hours = body.interval_hours

    await db.commit()
    await db.refresh(row)
    return _to_out(row)
