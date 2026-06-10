"""Per-source pricing for response cost estimation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenRate:
    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True, slots=True)
class FlatRate:
    per_call: float


PRICING: dict[str, TokenRate | FlatRate] = {
    "dataforseo": FlatRate(per_call=0.002),
    "brightdata_chatgpt": FlatRate(per_call=0.0015),
}


def estimate_cost(
    source: str,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> float | None:
    """USD cost for a single response. None if source is unpriced or
    token counts are required and missing."""
    rate = PRICING.get(source)
    if rate is None:
        return None

    if isinstance(rate, FlatRate):
        return rate.per_call

    if input_tokens is None and output_tokens is None:
        return None

    in_tok = input_tokens or 0
    out_tok = output_tokens or 0
    return in_tok * rate.input_per_mtok / 1_000_000 + out_tok * rate.output_per_mtok / 1_000_000
