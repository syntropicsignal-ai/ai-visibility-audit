"""Prompt-generator abstraction.

The prompt-generation algorithm is the central pluggable component of
this project. Routes inject the active generator via FastAPI's
`Depends(get_generator)`; swap implementations either by editing
`get_generator` below (in-repo / build-time) or by overriding the
dependency in test/plugin code:

    app.dependency_overrides[get_generator] = lambda: MyGenerator()
"""

from app.services.prompt_generator.base import (
    BUYER_STAGES,
    INTENT_NAMES,
    LENGTH_MODES,
    SEED_SOURCES,
    BuyerStage,
    GeneratedPrompt,
    GenerateRequest,
    GenerateResult,
    IntentName,
    LengthMode,
    PromptGenerator,
    SeedSource,
)
from app.services.prompt_generator.default import DefaultPromptGenerator


def get_generator() -> PromptGenerator:
    """FastAPI dependency: returns the active prompt-generator instance.

    Replace the body to wire in a different implementation; in tests,
    use `app.dependency_overrides[get_generator] = ...` instead.
    """
    return DefaultPromptGenerator()


__all__ = [
    "BUYER_STAGES",
    "INTENT_NAMES",
    "LENGTH_MODES",
    "SEED_SOURCES",
    "BuyerStage",
    "DefaultPromptGenerator",
    "GeneratedPrompt",
    "GenerateRequest",
    "GenerateResult",
    "IntentName",
    "LengthMode",
    "PromptGenerator",
    "SeedSource",
    "get_generator",
]
