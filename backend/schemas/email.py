from pydantic import BaseModel, Field, StrictInt, field_validator
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID, uuid4


class EmailAddress(BaseModel):
    name: Optional[str] = None
    address: str


class EmailSummary(BaseModel):
    id: int
    gmail_message_id: str
    gmail_thread_id: str
    subject: Optional[str] = None
    from_address: Optional[str] = None
    from_name: Optional[str] = None
    to_addresses: list = []
    date: Optional[datetime] = None
    snippet: Optional[str] = None
    is_read: bool = False
    is_starred: bool = False
    is_draft: bool = False
    is_sent: bool = False
    is_trash: bool = False
    is_spam: bool = False
    has_attachments: bool = False
    labels: list = []
    account_email: Optional[str] = None
    ai_category: Optional[str] = None
    ai_priority: Optional[int] = None
    ai_email_type: Optional[str] = None
    is_subscription: Optional[bool] = None
    needs_reply: Optional[bool] = None
    needs_reply_ignored: Optional[bool] = None
    unsubscribe_info: Optional[dict] = None

    # Thread digest fields (populated when a ThreadDigest exists for this thread)
    thread_digest_type: Optional[str] = None       # conversation_type
    thread_digest_summary: Optional[str] = None    # summary
    thread_digest_outcome: Optional[str] = None    # resolved_outcome
    thread_digest_resolved: Optional[bool] = None  # is_resolved
    thread_digest_count: Optional[int] = None      # message_count from digest

    model_config = {"from_attributes": True}


class EmailDetail(EmailSummary):
    account_id: int
    cc_addresses: list = []
    bcc_addresses: list = []
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    size_bytes: Optional[int] = None
    reply_to: Optional[str] = None
    message_id_header: Optional[str] = None
    in_reply_to: Optional[str] = None
    references_header: Optional[str] = None
    attachments: list["AttachmentResponse"] = []
    ai_summary: Optional[str] = None
    ai_action_items: Optional[list] = None
    ai_model_used: Optional[str] = None
    suggested_reply: Optional[str] = None
    reply_options: Optional[list] = None


class AttachmentResponse(BaseModel):
    id: int
    filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    is_inline: bool = False

    model_config = {"from_attributes": True}


class EmailListRequest(BaseModel):
    account_id: Optional[int] = None
    label: Optional[str] = None
    mailbox: str = "INBOX"
    page: int = 1
    page_size: int = 50
    sort_by: str = "date"
    sort_order: str = "desc"
    search: Optional[str] = None
    is_read: Optional[bool] = None
    is_starred: Optional[bool] = None
    ai_category: Optional[str] = None


class EmailListResponse(BaseModel):
    emails: list[EmailSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class ThreadResponse(BaseModel):
    thread_id: str
    subject: Optional[str] = None
    emails: list[EmailDetail]
    participants: list[EmailAddress] = []
    ai_summary: Optional[str] = None


class EmailActionRequest(BaseModel):
    email_ids: list[StrictInt] = Field(min_length=1, max_length=200)
    action: Literal[
        "mark_read",
        "mark_unread",
        "star",
        "unstar",
        "archive",
        "trash",
        "untrash",
        "spam",
        "unspam",
    ]
    idempotency_key: UUID = Field(default_factory=uuid4)
    label: Optional[str] = None

    @field_validator("email_ids")
    @classmethod
    def require_unique_email_ids(cls, value: list[int]) -> list[int]:
        if any(email_id <= 0 for email_id in value):
            raise ValueError("email_ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("email_ids must be unique")
        return value


class MailActionItemResponse(BaseModel):
    id: int
    email_id: Optional[int] = None
    account_id: int
    gmail_message_id: str
    sequence: int
    action: str
    state: str
    attempt_count: int
    next_attempt_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    applied_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MailActionOperationResponse(BaseModel):
    request_id: UUID
    idempotency_key: UUID
    action: str
    state: str
    accepted_count: int
    undo_until: datetime
    created_at: datetime
    items: list[MailActionItemResponse]


class ComposeAttachment(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    data_base64: str


class ComposeRequest(BaseModel):
    account_id: int
    to: list[str]
    cc: list[str] = []
    bcc: list[str] = []
    subject: str = ""
    body_html: str = ""
    body_text: str = ""
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    thread_id: Optional[str] = None
    is_draft: bool = False
    attachments: list[ComposeAttachment] = Field(default_factory=list)


class LabelResponse(BaseModel):
    id: int
    gmail_label_id: str
    name: str
    label_type: Optional[str] = None
    color_bg: Optional[str] = None
    color_text: Optional[str] = None
    messages_total: int = 0
    messages_unread: int = 0

    model_config = {"from_attributes": True}
