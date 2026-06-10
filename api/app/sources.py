from __future__ import annotations

from app.providers.base import LLMProvider
from app.providers.brightdata_chatgpt import BrightDataChatGPTProvider
from app.providers.brightdata_gemini import BrightDataGeminiProvider
from app.providers.brightdata_google_ai_mode import BrightDataGoogleAIModeProvider
from app.providers.dataforseo import DataForSEOProvider


# Insertion order drives UI ordering + analytics groupings.
SOURCES: dict[str, type[LLMProvider]] = {
    "dataforseo": DataForSEOProvider,
    "brightdata_chatgpt": BrightDataChatGPTProvider,
    "brightdata_google_ai_mode": BrightDataGoogleAIModeProvider,
    "brightdata_gemini": BrightDataGeminiProvider,
}

DISPLAY_NAMES: dict[str, str] = {
    "dataforseo": "Google AI Overview",
    "brightdata_chatgpt": "ChatGPT",
    "brightdata_google_ai_mode": "Google AI Mode",
    "brightdata_gemini": "Gemini",
}


def display_name(source_id: str) -> str:
    return DISPLAY_NAMES.get(source_id, source_id)


def all_source_ids() -> list[str]:
    return list(SOURCES.keys())
