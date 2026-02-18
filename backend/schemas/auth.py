from pydantic import BaseModel, field_validator
from typing import Optional


ALLOWED_MODELS = [
    "claude-opus-4-6",
    "claude-opus-4-6-fast",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
]

DEFAULT_AI_PREFERENCES = {
    "chat_plan_model": "claude-opus-4-6",
    "chat_execute_model": "claude-opus-4-6",
    "chat_verify_model": "claude-opus-4-6",
    "agentic_model": "claude-sonnet-4-5-20250929",
    "custom_prompt_model": "claude-sonnet-4-5-20250929",
}


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
    chat_execute_model: str
    chat_verify_model: str
    agentic_model: str
    custom_prompt_model: str
    allowed_models: list[str] = ALLOWED_MODELS


class AIPreferencesUpdate(BaseModel):
    chat_plan_model: Optional[str] = None
    chat_execute_model: Optional[str] = None
    chat_verify_model: Optional[str] = None
    agentic_model: Optional[str] = None
    custom_prompt_model: Optional[str] = None

    @field_validator("chat_plan_model", "chat_execute_model", "chat_verify_model", "agentic_model", "custom_prompt_model")
    @classmethod
    def validate_model_name(cls, v):
        if v is not None and v not in ALLOWED_MODELS:
            raise ValueError(f"Model must be one of: {', '.join(ALLOWED_MODELS)}")
        return v


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
