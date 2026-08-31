import base64
import re
from email.utils import formataddr, getaddresses

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from typing import Literal, Optional
from datetime import datetime, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class EmailAddress(BaseModel):
    name: Optional[str] = None
    address: str


class EmailSummary(BaseModel):
    id: int
    account_id: Optional[int] = None
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


class ConversationSummary(BaseModel):
    conversation_key: str
    account_id: int
    account_email: str
    anchor_email_id: int
    gmail_message_id: str
    gmail_thread_id: str
    subject: Optional[str] = None
    from_address: Optional[str] = None
    from_name: Optional[str] = None
    to_addresses: list = []
    date: Optional[datetime] = None
    snippet: Optional[str] = None
    is_draft: bool = False
    is_sent: bool = False
    is_trash: bool = False
    is_spam: bool = False
    is_read: bool
    unread_count: int
    is_starred: bool
    star_state: Literal["none", "some", "all"]
    has_attachments: bool
    labels: list[str] = []
    label_coverage: dict[str, Literal["some", "all"]] = {}
    member_count: int
    matched_count: int
    ai_category: Optional[str] = None
    ai_priority: Optional[int] = None
    ai_email_type: Optional[str] = None
    is_subscription: Optional[bool] = None
    needs_reply: Optional[bool] = None
    needs_reply_ignored: Optional[bool] = None
    unsubscribe_info: Optional[dict] = None
    thread_digest_type: Optional[str] = None
    thread_digest_summary: Optional[str] = None
    thread_digest_outcome: Optional[str] = None
    thread_digest_resolved: Optional[bool] = None
    thread_digest_count: Optional[int] = None
    inbox_placement: Optional[Literal["focused", "other"]] = None
    inbox_placement_reason: Optional[
        Literal[
            "high_priority",
            "needs_reply",
            "trusted_contact",
            "delegated_scheduling",
            "subscription",
            "low_priority",
            "unclassified",
            "direct_or_fyi",
        ]
    ] = None


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class ConversationSplitResponse(BaseModel):
    focused: ConversationListResponse
    other: ConversationListResponse
    total: int


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
        "unarchive",
        "trash",
        "untrash",
        "spam",
        "unspam",
        "add_label",
        "remove_label",
        "move_to_label",
    ]
    idempotency_key: UUID = Field(default_factory=uuid4)
    scope: Literal["messages", "conversations"] = "messages"
    label_id: Optional[StrictInt] = Field(default=None, gt=0)
    label: Optional[str] = None

    @field_validator("email_ids")
    @classmethod
    def require_unique_email_ids(cls, value: list[int]) -> list[int]:
        if any(email_id <= 0 for email_id in value):
            raise ValueError("email_ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("email_ids must be unique")
        return value

    @model_validator(mode="after")
    def require_label_id_only_for_label_actions(self):
        label_actions = {"add_label", "remove_label", "move_to_label"}
        if self.action in label_actions and self.label_id is None:
            raise ValueError("label_id is required for label actions")
        if self.action not in label_actions and self.label_id is not None:
            raise ValueError("label_id is only supported for label actions")
        return self


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


MAX_COMPOSE_RECIPIENTS = 100
MAX_COMPOSE_ATTACHMENT_COUNT = 10
MAX_COMPOSE_ATTACHMENT_BYTES = 18 * 1024 * 1024
MAX_COMPOSE_BODY_CHARS = 10 * 1024 * 1024
_EMAIL_ADDRESS_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


def _normalize_mailbox(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Recipients must be email addresses")
    raw = value.strip()
    if not raw or len(raw) > 998 or "\r" in raw or "\n" in raw:
        raise ValueError("Recipient address is invalid")
    parsed = getaddresses([raw])
    if len(parsed) != 1:
        raise ValueError("Recipient address is invalid")
    display_name, address = parsed[0]
    address = address.strip().lower()
    if not _EMAIL_ADDRESS_RE.fullmatch(address):
        raise ValueError("Recipient address is invalid")
    clean_name = display_name.replace("\r", "").replace("\n", "").strip()
    return formataddr((clean_name, address)) if clean_name else address


class ComposeAttachment(BaseModel):
    attachment_id: Optional[UUID] = None
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", min_length=1, max_length=255)
    data_base64: str = Field(min_length=1, max_length=25 * 1024 * 1024)

    @field_validator("filename", "content_type")
    @classmethod
    def validate_attachment_headers(cls, value: str) -> str:
        value = value.strip()
        if not value or "\r" in value or "\n" in value:
            raise ValueError("Attachment metadata is invalid")
        return value

    def decoded_size(self) -> int:
        try:
            return len(base64.b64decode(self.data_base64, validate=True))
        except (TypeError, ValueError) as exc:
            raise ValueError("Attachment data is not valid base64") from exc


class ComposeMessageBase(BaseModel):
    account_id: StrictInt = Field(gt=0)
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = Field(default="", max_length=998)
    body_html: str = Field(default="", max_length=MAX_COMPOSE_BODY_CHARS)
    body_text: str = Field(default="", max_length=MAX_COMPOSE_BODY_CHARS)
    in_reply_to: Optional[str] = Field(default=None, max_length=998)
    references: Optional[str] = Field(default=None, max_length=8192)
    thread_id: Optional[str] = Field(default=None, max_length=255)
    source_email_id: Optional[StrictInt] = Field(default=None, gt=0)
    is_draft: bool = False
    attachments: list[ComposeAttachment] = Field(default_factory=list)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def validate_recipient_list(cls, values: list[str]) -> list[str]:
        if len(values) > MAX_COMPOSE_RECIPIENTS:
            raise ValueError(f"A recipient field can include at most {MAX_COMPOSE_RECIPIENTS} addresses")
        normalized = [_normalize_mailbox(value) for value in values]
        identities = [getaddresses([value])[0][1].casefold() for value in normalized]
        if len(set(identities)) != len(identities):
            raise ValueError("Recipient addresses must be unique within each field")
        return normalized

    @field_validator("subject", "in_reply_to", "references", "thread_id")
    @classmethod
    def reject_header_newlines(cls, value: str | None) -> str | None:
        if value is not None and ("\r" in value or "\n" in value):
            raise ValueError("Message headers cannot contain newlines")
        return value

    @model_validator(mode="after")
    def validate_message_bounds(self):
        if len(self.to) + len(self.cc) + len(self.bcc) > MAX_COMPOSE_RECIPIENTS:
            raise ValueError(f"A message can include at most {MAX_COMPOSE_RECIPIENTS} recipients")
        identities = []
        for value in (*self.to, *self.cc, *self.bcc):
            parsed = getaddresses([value])
            identities.append(parsed[0][1].casefold())
        if len(set(identities)) != len(identities):
            raise ValueError("Recipient addresses must be unique across To, Cc, and Bcc")
        if len(self.attachments) > MAX_COMPOSE_ATTACHMENT_COUNT:
            raise ValueError(f"A message can include at most {MAX_COMPOSE_ATTACHMENT_COUNT} attachments")
        if sum(item.decoded_size() for item in self.attachments) > MAX_COMPOSE_ATTACHMENT_BYTES:
            raise ValueError("Attachments exceed the 18 MB message limit")
        return self


class ComposeRequest(ComposeMessageBase):
    idempotency_key: UUID
    client_draft_id: Optional[UUID] = None
    draft_revision: Optional[StrictInt] = Field(default=None, gt=0)
    scheduled_for: Optional[datetime] = None
    schedule_timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)
    archive_source_after_send: bool = False

    @field_validator("scheduled_for")
    @classmethod
    def normalize_scheduled_for(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Scheduled delivery requires a timezone-aware date and time")
        return value.astimezone(timezone.utc).replace(microsecond=0)

    @field_validator("schedule_timezone")
    @classmethod
    def validate_schedule_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_+./-]+", candidate):
            raise ValueError("Schedule timezone is invalid")
        try:
            ZoneInfo(candidate)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Schedule timezone is invalid") from error
        return candidate

    @model_validator(mode="after")
    def require_primary_recipient(self):
        if not self.to:
            raise ValueError("A message requires at least one To recipient")
        if self.is_draft:
            raise ValueError("The send endpoint does not accept draft payloads")
        if (self.client_draft_id is None) != (self.draft_revision is None):
            raise ValueError("A linked draft requires both client_draft_id and draft_revision")
        if self.schedule_timezone is not None and self.scheduled_for is None:
            raise ValueError("Schedule timezone requires a scheduled delivery time")
        if self.scheduled_for is not None and self.client_draft_id is None:
            raise ValueError("Scheduled delivery requires a safely saved draft")
        if self.archive_source_after_send and self.source_email_id is None:
            raise ValueError("Archiving after send requires an exact source email")
        return self


class ComposeDraftRequest(ComposeMessageBase):
    client_draft_id: UUID
    revision: StrictInt = Field(gt=0)
    mutation_id: UUID


class RecipientSuggestionResponse(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    address: str = Field(max_length=254)
    formatted: str = Field(max_length=998)

    model_config = {"from_attributes": True}


class RecipientSuggestionListResponse(BaseModel):
    suggestions: list[RecipientSuggestionResponse]


DraftSessionState = Literal[
    "pending",
    "syncing",
    "reconciling",
    "synced",
    "failed",
    "discard_pending",
    "discarded",
    "sending",
]


class DraftMutationRequest(BaseModel):
    mutation_id: UUID


class DraftAttachmentDetail(BaseModel):
    attachment_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    data_base64: str


class DraftSessionResponse(BaseModel):
    client_draft_id: UUID
    account_id: int
    source_email_id: Optional[int] = None
    revision: int
    synced_revision: Optional[int] = None
    state: DraftSessionState
    next_attempt_at: Optional[datetime] = None
    attempt_count: int
    can_undo_discard: bool
    discard_at: Optional[datetime] = None
    discard_undo_until: Optional[datetime] = None
    linked_send_id: Optional[UUID] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attachment_count: int = 0
    attachment_bytes: int = 0
    created_at: datetime
    updated_at: datetime
    synced_at: Optional[datetime] = None
    discarded_at: Optional[datetime] = None


class DraftSessionDetailResponse(DraftSessionResponse):
    to: list[str] = []
    cc: list[str] = []
    bcc: list[str] = []
    subject: str = ""
    body_html: str = ""
    body_text: str = ""
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    thread_id: Optional[str] = None
    attachments: list[DraftAttachmentDetail] = []


OutboundSendState = Literal[
    "staged",
    "processing",
    "retry_wait",
    "reconciling",
    "sent",
    "failed",
    "cancelled",
]


class OutboundSendResponse(BaseModel):
    send_id: UUID
    idempotency_key: UUID
    account_id: int
    source_email_id: Optional[int] = None
    archive_source_after_send: bool = False
    client_draft_id: Optional[UUID] = None
    state: OutboundSendState
    scheduled_for: Optional[datetime] = None
    schedule_timezone: Optional[str] = None
    execute_after: datetime
    undo_until: datetime
    next_attempt_at: Optional[datetime] = None
    attempt_count: int
    max_attempts: int
    can_undo: bool
    can_cancel: bool
    can_send_now: bool
    can_retry: bool
    provider_message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LabelResponse(BaseModel):
    id: int
    account_id: int
    gmail_label_id: str
    name: str
    label_type: Optional[str] = None
    color_bg: Optional[str] = None
    color_text: Optional[str] = None
    messages_total: int = 0
    messages_unread: int = 0

    model_config = {"from_attributes": True}
