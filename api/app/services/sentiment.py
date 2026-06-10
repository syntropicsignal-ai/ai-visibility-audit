"""Per-response brand-mention classifier (one LLM call per response,
not per response × brand). Skipped when zero brands detected."""

import json
import logging
from collections.abc import Sequence
from typing import TypedDict

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    OpenAIError,
    RateLimitError,
)

from app.config import settings
from app.models import Sentiment

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You analyze how a piece of text speaks about specific brands. "
    "For each brand in the provided list, decide two things:\n"
    '  1. "sentiment": "positive", "neutral", or "negative" — how the '
    'text speaks about that brand. Use "neutral" if the brand is '
    "mentioned but the text expresses no clear opinion.\n"
    '  2. "recommended": true or false — whether the text actively '
    'recommends or endorses that brand to the reader (e.g. "I '
    'recommend X", "X is a solid choice", "go with X", "X is the '
    'best option", listing X as a top pick). A neutral mention or a '
    "passing reference is NOT a recommendation. A negative mention is "
    "never a recommendation.\n"
    "Reply with a JSON object whose keys are the exact brand names you "
    'were given and whose values are objects with "sentiment" and '
    '"recommended" fields. Output JSON only — no prose, no code fences.'
)


class BrandClassification(TypedDict):
    sentiment: Sentiment
    recommended: bool


_VALID: dict[str, Sentiment] = {
    "positive": Sentiment.positive,
    "neutral": Sentiment.neutral,
    "negative": Sentiment.negative,
}


async def classify_brand_mentions(
    text: str, brand_names: Sequence[str]
) -> dict[str, BrandClassification]:
    """Classify per-brand sentiment AND recommendation for one response.

    Returns a dict mapping each input brand name to a dict with `sentiment`
    and `recommended`. Brands the classifier omits or returns malformed
    values for fall back to `(neutral, False)` — they were detected as
    mentioned, so "neutral" is a safer default than "not_mentioned" (which
    would contradict the detection step). On any provider failure this
    function logs at ERROR and returns an empty dict; the caller is
    responsible for falling back to `Sentiment.not_mentioned` and
    `recommended=False` for those rows.
    """
    if not brand_names or not text.strip():
        return {}
    if not settings.gemini_api_key:
        logger.warning("Sentiment classifier disabled: GEMINI_API_KEY not configured")
        return {}

    user_prompt = "Brands to classify: " + ", ".join(brand_names) + "\n\nText:\n" + text

    client = AsyncOpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)
    try:
        completion = await client.chat.completions.create(
            model=settings.sentiment_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
    except (
        AuthenticationError,
        BadRequestError,
        RateLimitError,
        APIConnectionError,
        APITimeoutError,
        APIStatusError,
        OpenAIError,
    ) as e:
        logger.error("Sentiment classifier call failed: %s", e)
        return {}

    raw = completion.choices[0].message.content if completion.choices else None
    if not raw:
        logger.error("Sentiment classifier returned empty content")
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Sentiment classifier returned non-JSON: %s — raw=%r", e, raw)
        return {}

    if not isinstance(data, dict):
        logger.error("Sentiment classifier JSON wasn't an object: %r", data)
        return {}

    result: dict[str, BrandClassification] = {}
    for name in brand_names:
        entry = data.get(name)
        sentiment = Sentiment.neutral
        recommended = False
        if isinstance(entry, dict):
            sval = entry.get("sentiment")
            if isinstance(sval, str) and sval.lower() in _VALID:
                sentiment = _VALID[sval.lower()]
            rval = entry.get("recommended")
            if isinstance(rval, bool):
                recommended = rval
        elif isinstance(entry, str) and entry.lower() in _VALID:
            # Tolerate the old flat shape in case the model regresses to it.
            sentiment = _VALID[entry.lower()]
        result[name] = {"sentiment": sentiment, "recommended": recommended}
    return result
