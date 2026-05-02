"""Central registry of Claude model identifiers used by the application.

All other modules MUST import from here so that adding, removing, or renaming
a model is a single-file change.

Model naming convention:
    A trailing "-fast" suffix means "use this model with the
    `fast-mode-2026-02-01` Anthropic beta header" (handled in
    `backend/services/ai.py::AIService._call_claude`). The base model id is
    obtained by stripping that suffix.

Computer Use models map to a (beta_header, tool_type) tuple in CU_CONFIG;
this lives alongside the other model metadata so a model bump here cannot
silently break the unsubscribe flow.
"""
from __future__ import annotations

# The single small/cheap model used for non-user-visible classifications
# (e.g. short labels, "expects reply?" sent-email checks).
CHEAP_MODEL = "claude-haiku-4-5-20251001"


# Model registry: ordered for the UI dropdown.
# Each entry is (id, human-readable label).
MODEL_REGISTRY: list[tuple[str, str]] = [
    ("claude-opus-4-7", "Claude Opus 4.7 — Most capable"),
    ("claude-opus-4-7-fast", "Claude Opus 4.7 (Fast) — 2.5x speed, 6x cost"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 — Balanced"),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5 — Fastest"),
]

ALLOWED_MODELS: list[str] = [model_id for model_id, _ in MODEL_REGISTRY]
MODEL_LABELS: dict[str, str] = {model_id: label for model_id, label in MODEL_REGISTRY}


# Per-feature defaults. Keys must match `AIPreferencesResponse` fields.
DEFAULT_AI_PREFERENCES: dict[str, str] = {
    "chat_plan_model": "claude-opus-4-7",
    "chat_execute_model": "claude-opus-4-7",
    "chat_verify_model": "claude-opus-4-7",
    "agentic_model": "claude-sonnet-4-6",
    "custom_prompt_model": "claude-sonnet-4-6",
    "unsubscribe_model": "claude-sonnet-4-6",
}


# Computer Use beta + tool-type per model. Models not listed here cannot be
# used for the AI-powered unsubscribe flow.
CU_CONFIG: dict[str, tuple[str, str]] = {
    "claude-opus-4-7": ("computer-use-2025-11-24", "computer_20251124"),
    "claude-opus-4-7-fast": ("computer-use-2025-11-24", "computer_20251124"),
    "claude-sonnet-4-6": ("computer-use-2025-11-24", "computer_20251124"),
    "claude-haiku-4-5-20251001": ("computer-use-2025-01-24", "computer_20250124"),
}
DEFAULT_CU_MODEL = "claude-sonnet-4-6"


def base_model_id(model: str) -> str:
    """Strip the `-fast` suffix to get the underlying Anthropic model id."""
    return model.removesuffix("-fast")


def is_fast_variant(model: str) -> bool:
    return model.endswith("-fast")


def is_valid_model(model: str | None) -> bool:
    return model is not None and model in ALLOWED_MODELS
