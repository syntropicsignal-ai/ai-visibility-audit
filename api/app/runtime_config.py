"""Runtime settings overlay (data/config.json) for keys the setup UI sets."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).resolve().parent.parent / "data" / "config.json"

CONFIGURABLE_KEYS: frozenset[str] = frozenset(
    {
        "gemini_api_key",
        "openai_api_key",
        "exa_api_key",
        "dataforseo_login",
        "dataforseo_password",
        "brightdata_api_key",
        "brightdata_chatgpt_dataset_id",
        "brightdata_gemini_dataset_id",
        "brightdata_google_ai_mode_dataset_id",
    }
)

REQUIRED_KEYS: frozenset[str] = frozenset(
    {"gemini_api_key", "exa_api_key", "dataforseo_login", "dataforseo_password"}
)


def load_runtime_config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to read runtime config at %s", CONFIG_FILE)
        return {}
    return {k: v for k, v in data.items() if k in CONFIGURABLE_KEYS and isinstance(v, str)}


def apply_runtime_config(values: dict[str, str]) -> None:
    for key, val in values.items():
        if key in CONFIGURABLE_KEYS and isinstance(val, str) and val:
            setattr(settings, key, val)


def save_runtime_config(values: dict[str, str]) -> dict[str, str]:
    # Empty / whitespace-only values are skipped so partial form
    # submissions don't clear existing keys.
    current = load_runtime_config()
    for key, val in values.items():
        if key not in CONFIGURABLE_KEYS:
            continue
        if not isinstance(val, str):
            continue
        v = val.strip()
        if v:
            current[key] = v
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(current, indent=2))
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
    apply_runtime_config(current)
    return current


def configured_keys() -> dict[str, bool]:
    return {k: bool(getattr(settings, k, "")) for k in CONFIGURABLE_KEYS}


def setup_required() -> bool:
    return any(not bool(getattr(settings, k, "")) for k in REQUIRED_KEYS)
