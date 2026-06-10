"""Read-only credential-status panel for the predefined sources."""

from fastapi import APIRouter

from app.schemas import SourceStatus
from app.sources import SOURCES, display_name

router = APIRouter()


@router.get("", response_model=list[SourceStatus])
async def list_sources() -> list[SourceStatus]:
    """One row per registered source, in registry order. Each row tells the
    UI: id, display name, whether credentials are configured right now,
    and a hint pointing at the env var(s) to set if they aren't."""
    return [
        SourceStatus(
            id=source_id,
            display_name=display_name(source_id),
            configured=provider_cls.is_configured(),
            credential_hint=provider_cls.credential_hint(),
        )
        for source_id, provider_cls in SOURCES.items()
    ]
