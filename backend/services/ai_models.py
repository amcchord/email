"""Provider-aware AI model registry and per-workload defaults.

The user preference JSON stores a model and an effort level for each workload.
Keeping capability metadata here lets the API, workers, and settings UI agree
on which combinations are valid without a database migration.
"""
from __future__ import annotations

from dataclasses import dataclass


OPENAI_EFFORT_LEVELS = ("none", "low", "medium", "high", "xhigh", "max")
ANTHROPIC_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

MODEL_PREFERENCE_KEYS = (
    "chat_plan_model",
    "chat_execute_model",
    "chat_verify_model",
    "agentic_model",
    "custom_prompt_model",
    "unsubscribe_model",
)


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    provider: str
    effort_levels: tuple[str, ...]
    default_effort: str
    preference_keys: tuple[str, ...] = MODEL_PREFERENCE_KEYS


_GENERAL_KEYS = tuple(k for k in MODEL_PREFERENCE_KEYS if k != "unsubscribe_model")

# Ordered for the settings UI. OpenAI models use the Responses API. The
# unsubscribe workflow remains on Claude because its current browser loop uses
# Anthropic's Computer Use protocol.
MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "gpt-5.6-sol",
        "GPT-5.6 Sol — Flagship",
        "openai",
        OPENAI_EFFORT_LEVELS,
        "medium",
        _GENERAL_KEYS,
    ),
    ModelSpec(
        "gpt-5.6-terra",
        "GPT-5.6 Terra — Balanced",
        "openai",
        OPENAI_EFFORT_LEVELS,
        "medium",
        _GENERAL_KEYS,
    ),
    ModelSpec(
        "gpt-5.6-luna",
        "GPT-5.6 Luna — Efficient",
        "openai",
        OPENAI_EFFORT_LEVELS,
        "low",
        _GENERAL_KEYS,
    ),
    ModelSpec(
        "claude-fable-5",
        "Claude Fable 5 — Frontier",
        "anthropic",
        ANTHROPIC_EFFORT_LEVELS,
        "high",
    ),
    ModelSpec(
        "claude-opus-5",
        "Claude Opus 5 — Agentic",
        "anthropic",
        ANTHROPIC_EFFORT_LEVELS,
        "high",
    ),
    ModelSpec(
        "claude-sonnet-5",
        "Claude Sonnet 5 — Fast + capable",
        "anthropic",
        ANTHROPIC_EFFORT_LEVELS,
        "medium",
    ),
)

MODEL_REGISTRY: list[tuple[str, str]] = [(spec.id, spec.label) for spec in MODEL_SPECS]
MODEL_BY_ID: dict[str, ModelSpec] = {spec.id: spec for spec in MODEL_SPECS}
ALLOWED_MODELS: list[str] = [spec.id for spec in MODEL_SPECS]
MODEL_LABELS: dict[str, str] = {spec.id: spec.label for spec in MODEL_SPECS}
MODEL_PROVIDERS: dict[str, str] = {spec.id: spec.provider for spec in MODEL_SPECS}
MODEL_EFFORT_LEVELS: dict[str, list[str]] = {
    spec.id: list(spec.effort_levels) for spec in MODEL_SPECS
}
MODELS_BY_PREFERENCE: dict[str, list[str]] = {
    key: [spec.id for spec in MODEL_SPECS if key in spec.preference_keys]
    for key in MODEL_PREFERENCE_KEYS
}


# Smart defaults match each workload's shape instead of paying flagship rates
# everywhere: balanced planning, efficient parallel retrieval and bulk triage,
# a high-quality final synthesis, and Claude Computer Use for unsubscribe.
DEFAULT_AI_PREFERENCES: dict[str, str] = {
    "chat_plan_model": "gpt-5.6-terra",
    "chat_plan_effort": "medium",
    "chat_execute_model": "gpt-5.6-luna",
    "chat_execute_effort": "low",
    "chat_verify_model": "gpt-5.6-sol",
    "chat_verify_effort": "high",
    "agentic_model": "gpt-5.6-luna",
    "agentic_effort": "low",
    "custom_prompt_model": "gpt-5.6-terra",
    "custom_prompt_effort": "medium",
    "unsubscribe_model": "claude-sonnet-5",
    "unsubscribe_effort": "medium",
}

# The small/cheap model used for non-user-visible classifications.
CHEAP_MODEL = "gpt-5.6-luna"
CHEAP_MODEL_EFFORT = "low"


# Existing unsubscribe code uses the earlier Computer Use tool protocol. All
# three requested Claude 5 models support this compatibility version.
CU_CONFIG: dict[str, tuple[str, str]] = {
    "claude-fable-5": ("computer-use-2025-11-24", "computer_20251124"),
    "claude-opus-5": ("computer-use-2025-11-24", "computer_20251124"),
    "claude-sonnet-5": ("computer-use-2025-11-24", "computer_20251124"),
}
DEFAULT_CU_MODEL = DEFAULT_AI_PREFERENCES["unsubscribe_model"]


def base_model_id(model: str) -> str:
    """Return the provider model id (legacy ``-fast`` aliases are stripped)."""
    return model.removesuffix("-fast")


def is_fast_variant(model: str) -> bool:
    return model.endswith("-fast")


def is_valid_model(model: str | None) -> bool:
    return model is not None and model in MODEL_BY_ID


def provider_for_model(model: str) -> str:
    spec = MODEL_BY_ID.get(model)
    if not spec:
        raise ValueError(f"Unsupported AI model: {model}")
    return spec.provider


def is_model_allowed_for_preference(model: str, preference_key: str) -> bool:
    return model in MODELS_BY_PREFERENCE.get(preference_key, ())


def default_effort_for_model(model: str) -> str:
    spec = MODEL_BY_ID.get(model)
    if not spec:
        raise ValueError(f"Unsupported AI model: {model}")
    return spec.default_effort


def is_valid_effort(model: str, effort: str | None) -> bool:
    spec = MODEL_BY_ID.get(model)
    return bool(spec and effort in spec.effort_levels)


def resolve_effort(model: str, effort: str | None) -> str:
    """Return a valid effort for *model*, falling back to its model default."""
    if is_valid_effort(model, effort):
        return str(effort)
    return default_effort_for_model(model)
