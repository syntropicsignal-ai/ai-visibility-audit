from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Analysis, Brand, IntentType, Response, Run
from app.schemas import BrandAnalysis, ResponseDetail, RunOut, ShoppingProductOut
from app.services.shopping import match_product_brand, product_from_row
from app.sources import display_name

router = APIRouter()


def _serialize_shopping(resp: Response, brands: list[Brand]) -> list[ShoppingProductOut] | None:
    if not resp.shopping_results:
        return None
    out: list[ShoppingProductOut] = []
    for row in resp.shopping_results:
        product = product_from_row(row)
        matched = match_product_brand(product, brands)
        out.append(
            ShoppingProductOut(
                position=product.position,
                title=product.title,
                price=product.price,
                rating=product.rating,
                reviews=product.reviews,
                image=product.image,
                link=product.link,
                description=product.description,
                tag=product.tag,
                brand_id=matched.id if matched else None,
                brand_name=matched.name if matched else None,
                is_self=matched.is_self if matched else False,
            )
        )
    return out


class TriggerRunRequest(BaseModel):
    brand_id: int


@router.get("", response_model=list[RunOut])
async def list_runs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Run).order_by(Run.started_at.desc()))
    return result.scalars().all()


@router.post("", response_model=RunOut, status_code=201)
async def trigger_run(data: TriggerRunRequest, db: AsyncSession = Depends(get_db)):
    from app.services.run_service import execute_run

    try:
        run = await execute_run(db, brand_id=data.brand_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return run


@router.get("/{run_id}/responses", response_model=list[ResponseDetail])
async def list_run_responses(
    run_id: int,
    source: str | None = Query(None, description="Filter to a single source_id"),
    intent: IntentType | None = Query(None),
    mentioned: bool | None = Query(
        None, description="If set, only responses where self brand was/wasn't found"
    ),
    failed: bool | None = Query(
        None, description="If true, only failed responses; if false, only successful"
    ),
    q: str | None = Query(None, description="Substring search in prompt or response text"),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    query = (
        select(Response)
        .where(Response.run_id == run_id)
        .options(
            selectinload(Response.prompt),
            selectinload(Response.analyses).selectinload(Analysis.brand),
        )
        .order_by(Response.prompt_id, Response.source)
    )
    if source is not None:
        query = query.where(Response.source == source)
    if failed is True:
        query = query.where(Response.error_kind.is_not(None))
    elif failed is False:
        query = query.where(Response.error_kind.is_(None))

    rows = list((await db.execute(query)).scalars().all())

    brands = list((await db.execute(select(Brand))).scalars().all())
    self_brand_ids = {b.id for b in brands if b.is_self}

    out: list[ResponseDetail] = []
    for resp in rows:
        if intent is not None and resp.prompt.intent != intent:
            continue
        if q:
            needle = q.lower()
            if needle not in resp.text.lower() and needle not in resp.prompt.text.lower():
                continue
        if mentioned is not None:
            self_found = any(a.brand_found for a in resp.analyses if a.brand_id in self_brand_ids)
            if mentioned != self_found:
                continue

        out.append(
            ResponseDetail(
                id=resp.id,
                run_id=resp.run_id,
                prompt_id=resp.prompt_id,
                prompt_text=resp.prompt.text,
                prompt_intent=resp.prompt.intent,
                source=resp.source,
                source_name=display_name(resp.source),
                text=resp.text,
                tokens_used=resp.tokens_used,
                latency_ms=resp.latency_ms,
                source_urls=resp.source_urls,
                search_queries=resp.search_queries,
                shopping_products=_serialize_shopping(resp, brands),
                error_kind=resp.error_kind,
                error_message=resp.error_message,
                created_at=resp.created_at,
                analyses=[
                    BrandAnalysis(
                        brand_id=a.brand_id,
                        brand_name=a.brand.name,
                        is_self=a.brand.is_self,
                        brand_found=a.brand_found,
                        sentiment=a.sentiment,
                        recommended=a.recommended,
                        link_present=a.link_present,
                        our_pages=a.our_pages,
                        competitors=a.competitors,
                    )
                    for a in resp.analyses
                ],
            )
        )
    return out
