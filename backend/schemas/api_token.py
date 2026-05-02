from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ApiTokenCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class ApiTokenSummary(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiTokenCreatedResponse(BaseModel):
    """Returned exactly once at creation: includes the raw token."""
    id: int
    name: str
    prefix: str
    token: str
    created_at: datetime
