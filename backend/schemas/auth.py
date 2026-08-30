from pydantic import BaseModel, field_validator, model_validator
from typing import Optional

from backend.services.ai_models import (
    ALLOWED_MODELS,
    DEFAULT_AI_PREFERENCES,
    MODEL_EFFORT_LEVELS,
    MODEL_LABELS,
    MODEL_PROVIDERS,
    MODELS_BY_PREFERENCE,
    is_model_allowed_for_preference,
    is_valid_effort,
)

# Re-exported here for backwards compatibility with existing imports.
__all__ = [
    "ALLOWED_MODELS",
    "DEFAULT_AI_PREFERENCES",
    "MODEL_LABELS",
    "LoginRequest",
    "TokenResponse",
    "RefreshRequest",
    "UserResponse",
    "AIPreferencesResponse",
    "AIPreferencesUpdate",
    "AboutMeResponse",
    "AboutMeUpdate",
    "AccountDescriptionUpdate",
    "KeyboardShortcutsResponse",
    "KeyboardShortcutsUpdate",
    "ALLOWED_THEMES",
    "ALLOWED_COLOR_SCHEMES",
    "DEFAULT_UI_PREFERENCES",
    "UIPreferencesResponse",
    "UIPreferencesUpdate",
]


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: Optional[str] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_admin: bool = False

    model_config = {"from_attributes": True}


class AIPreferencesResponse(BaseModel):
    chat_plan_model: str
    chat_plan_effort: str
    chat_execute_model: str
    chat_execute_effort: str
    chat_verify_model: str
    chat_verify_effort: str
    agentic_model: str
    agentic_effort: str
    custom_prompt_model: str
    custom_prompt_effort: str
    unsubscribe_model: str
    unsubscribe_effort: str
    allowed_models: list[str] = ALLOWED_MODELS
    # `model_` prefix is reserved by Pydantic v2; use `labels` instead.
    labels: dict[str, str] = MODEL_LABELS
    providers: dict[str, str] = MODEL_PROVIDERS
    effort_levels: dict[str, list[str]] = MODEL_EFFORT_LEVELS
    models_by_preference: dict[str, list[str]] = MODELS_BY_PREFERENCE


class AIPreferencesUpdate(BaseModel):
    chat_plan_model: Optional[str] = None
    chat_plan_effort: Optional[str] = None
    chat_execute_model: Optional[str] = None
    chat_execute_effort: Optional[str] = None
    chat_verify_model: Optional[str] = None
    chat_verify_effort: Optional[str] = None
    agentic_model: Optional[str] = None
    agentic_effort: Optional[str] = None
    custom_prompt_model: Optional[str] = None
    custom_prompt_effort: Optional[str] = None
    unsubscribe_model: Optional[str] = None
    unsubscribe_effort: Optional[str] = None

    @field_validator("chat_plan_model", "chat_execute_model", "chat_verify_model", "agentic_model", "custom_prompt_model", "unsubscribe_model")
    @classmethod
    def validate_model_name(cls, v):
        if v is not None and v not in ALLOWED_MODELS:
            raise ValueError(f"Model must be one of: {', '.join(ALLOWED_MODELS)}")
        return v

    @field_validator(
        "chat_plan_effort",
        "chat_execute_effort",
        "chat_verify_effort",
        "agentic_effort",
        "custom_prompt_effort",
        "unsubscribe_effort",
    )
    @classmethod
    def validate_effort_name(cls, v):
        allowed = {level for levels in MODEL_EFFORT_LEVELS.values() for level in levels}
        if v is not None and v not in allowed:
            raise ValueError(f"Effort must be one of: {', '.join(sorted(allowed))}")
        return v

    @model_validator(mode="after")
    def validate_model_effort_pairs(self):
        for key in (
            "chat_plan_model",
            "chat_execute_model",
            "chat_verify_model",
            "agentic_model",
            "custom_prompt_model",
            "unsubscribe_model",
        ):
            model = getattr(self, key)
            effort = getattr(self, key.removesuffix("_model") + "_effort")
            if model and not is_model_allowed_for_preference(model, key):
                raise ValueError(f"{model} is not supported for {key}")
            if model and effort and not is_valid_effort(model, effort):
                raise ValueError(f"{effort} effort is not supported by {model}")
        return self


class AboutMeResponse(BaseModel):
    about_me: Optional[str] = None


class AboutMeUpdate(BaseModel):
    about_me: Optional[str] = None


class AccountDescriptionUpdate(BaseModel):
    description: Optional[str] = None


class KeyboardShortcutsResponse(BaseModel):
    shortcuts: dict[str, str] = {}


class KeyboardShortcutsUpdate(BaseModel):
    shortcuts: dict[str, str] = {}


ALLOWED_THEMES = ["amber", "blue", "rose", "emerald", "purple", "mono"]
ALLOWED_COLOR_SCHEMES = ["light", "dark", "system"]

DEFAULT_UI_PREFERENCES = {
    "thread_order": "newest_first",
    "theme": "amber",
    "color_scheme": "light",
}


class UIPreferencesResponse(BaseModel):
    thread_order: str = "newest_first"
    theme: str = "amber"
    color_scheme: str = "light"


class UIPreferencesUpdate(BaseModel):
    thread_order: Optional[str] = None
    theme: Optional[str] = None
    color_scheme: Optional[str] = None

    @field_validator("thread_order")
    @classmethod
    def validate_thread_order(cls, v):
        if v is not None and v not in ("newest_first", "oldest_first"):
            raise ValueError("thread_order must be 'newest_first' or 'oldest_first'")
        return v

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, v):
        if v is not None and v not in ALLOWED_THEMES:
            raise ValueError(f"theme must be one of: {', '.join(ALLOWED_THEMES)}")
        return v

    @field_validator("color_scheme")
    @classmethod
    def validate_color_scheme(cls, v):
        if v is not None and v not in ALLOWED_COLOR_SCHEMES:
            raise ValueError(f"color_scheme must be one of: {', '.join(ALLOWED_COLOR_SCHEMES)}")
        return v
