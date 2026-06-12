"""Runtime-config endpoints.

Powers the setup dialog in the web UI. Status is read-only and never
returns key values — only booleans for whether each capability is
configured. POST /keys writes the runtime overlay (data/config.json)
and applies it to the in-process settings singleton.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.runtime_config import (
    CONFIGURABLE_KEYS,
    REQUIRED_KEYS,
    configured_keys,
    save_runtime_config,
    setup_required,
)

router = APIRouter()


class ConfigStatus(BaseModel):
    setup_required: bool
    required_keys: list[str]
    configurable_keys: list[str]
    configured: dict[str, bool]


class ConfigKeysUpdate(BaseModel):
    gemini_api_key: str | None = Field(default=None)
    exa_api_key: str | None = Field(default=None)
    dataforseo_login: str | None = Field(default=None)
    dataforseo_password: str | None = Field(default=None)
    brightdata_api_key: str | None = Field(default=None)
    brightdata_chatgpt_dataset_id: str | None = Field(default=None)
    brightdata_gemini_dataset_id: str | None = Field(default=None)
    brightdata_google_ai_mode_dataset_id: str | None = Field(default=None)


@router.get("/status", response_model=ConfigStatus)
async def get_status() -> ConfigStatus:
    return ConfigStatus(
        setup_required=setup_required(),
        required_keys=sorted(REQUIRED_KEYS),
        configurable_keys=sorted(CONFIGURABLE_KEYS),
        configured=configured_keys(),
    )


@router.post("/keys", response_model=ConfigStatus)
async def update_keys(body: ConfigKeysUpdate) -> ConfigStatus:
    submitted = {k: v for k, v in body.model_dump().items() if v is not None}
    save_runtime_config(submitted)
    return await get_status()
