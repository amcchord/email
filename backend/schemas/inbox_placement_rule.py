"""Strict API contracts for local user-trainable Inbox placement rules."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT = 500
InboxPlacementRuleScope = Literal["conversation", "sender", "domain"]
InboxPlacement = Literal["focused", "other"]


class InboxPlacementRuleUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    create_id: UUID
    account_id: StrictInt = Field(gt=0)
    anchor_email_id: StrictInt = Field(gt=0)
    scope: InboxPlacementRuleScope
    placement: InboxPlacement
    enabled: StrictBool = True
    expected_revision: StrictInt = Field(ge=0)


class InboxPlacementRuleReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    placement: InboxPlacement
    enabled: StrictBool
    revision: StrictInt = Field(gt=0)


class InboxPlacementRuleResponse(BaseModel):
    id: UUID
    account_id: int
    account_email: str
    scope: InboxPlacementRuleScope
    display_value: str
    placement: InboxPlacement
    enabled: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class InboxPlacementRuleListResponse(BaseModel):
    items: list[InboxPlacementRuleResponse]
    max_rules_per_account: int = MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT


class InboxPlacementRuleCandidateResponse(BaseModel):
    account_id: int
    account_email: str
    anchor_email_id: int
    conversation_label: str
    sender_address: str
    sender_domain: str
    rules: list[InboxPlacementRuleResponse]
