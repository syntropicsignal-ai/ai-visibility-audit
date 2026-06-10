from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.geo_catalog import (
    COUNTRIES,
    LANGUAGES,
    CountryCode,
    LanguageCode,
    get_country,
    get_language,
)
from app.models import Brand
from app.schemas import (
    BrandCreate,
    BrandOut,
    BrandUpdate,
    GeoCountryOut,
    GeoLanguageOut,
    GeoOptionsOut,
)

router = APIRouter()


@router.get("/geo-options", response_model=GeoOptionsOut)
async def list_geo_options() -> GeoOptionsOut:
    """Return curated countries and languages for brand geo dropdowns."""
    return GeoOptionsOut(
        countries=[
            GeoCountryOut(
                country_code=c.iso_code,
                name=c.name,
                default_language_code=c.default_language_code,
            )
            for c in COUNTRIES
        ],
        languages=[GeoLanguageOut(code=lang.code, name=lang.name) for lang in LANGUAGES],
    )


@router.get("", response_model=list[BrandOut])
async def list_brands(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Brand).order_by(Brand.is_self.desc(), Brand.name))
    return result.scalars().all()


def _resolve_geo(country_code: str, language_code: str) -> tuple[str, str]:
    """Validate codes against the catalog and return their display names.

    Raises HTTPException(400) if either code is unknown — UI dropdowns are
    populated from the same catalog so this should only fire on a stale
    client or a manual API call.
    """
    country = get_country(CountryCode(country_code))
    if country is None:
        raise HTTPException(status_code=400, detail=f"Unknown country_code: {country_code}")
    language = get_language(LanguageCode(language_code))
    if language is None:
        raise HTTPException(status_code=400, detail=f"Unknown language_code: {language_code}")
    return country.name, language.name


@router.post("", response_model=BrandOut, status_code=201)
async def create_brand(data: BrandCreate, db: AsyncSession = Depends(get_db)):
    country_name, language_name = _resolve_geo(data.country_code, data.language_code)
    brand = Brand(
        name=data.name,
        domains=data.domains,
        aliases=data.aliases,
        is_self=data.is_self,
        country_code=data.country_code,
        country_name=country_name,
        language_code=data.language_code,
        language_name=language_name,
    )
    db.add(brand)
    await db.commit()
    await db.refresh(brand)
    return brand


@router.get("/{brand_id}", response_model=BrandOut)
async def get_brand(brand_id: int, db: AsyncSession = Depends(get_db)):
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    return brand


@router.put("/{brand_id}", response_model=BrandOut)
async def update_brand(brand_id: int, data: BrandUpdate, db: AsyncSession = Depends(get_db)):
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    updates = data.model_dump(exclude_unset=True)

    # Geo validation: if either code is being updated, re-resolve both names
    # against the (possibly new) codes so the stored display names stay in sync.
    if "country_code" in updates or "language_code" in updates:
        new_country = updates.get("country_code", brand.country_code)
        new_language = updates.get("language_code", brand.language_code)
        country_name, language_name = _resolve_geo(new_country, new_language)
        updates["country_name"] = country_name
        updates["language_name"] = language_name

    for key, value in updates.items():
        setattr(brand, key, value)
    await db.commit()
    await db.refresh(brand)
    return brand


@router.delete("/{brand_id}", status_code=204)
async def delete_brand(brand_id: int, db: AsyncSession = Depends(get_db)):
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    await db.delete(brand)
    await db.commit()
