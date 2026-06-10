"""Demo-dataset routes (thin wrappers — safety interlocks live in
app.services.demo_seed; routes just turn ValueError into 409)."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.demo_seed import clear_demo, demo_status, seed_demo

router = APIRouter()


@router.get("/status")
async def get_demo_status(db: AsyncSession = Depends(get_db)) -> dict:
    return await demo_status(db)


@router.post("/seed")
async def post_demo_seed(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        summary = await seed_demo(db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"seeded": True, **asdict(summary)}


@router.post("/clear")
async def post_demo_clear(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await clear_demo(db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
