from pydantic import BaseModel
from typing import Optional
from datetime import datetime


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
    has_attachments: bool = False
    labels: list = []
    account_email: Optional[str] = None
    ai_category: Optional[str] = None
    ai_priority: Optional[int] = None

    model_config = {"from_attributes": True}


class EmailDetail(EmailSummary):
    cc_addresses: list = []
    bcc_addresses: list = []
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    size_bytes: Optional[int] = None
    reply_to: Optional[str] = None
    message_id_header: Optional[str] = None
    in_reply_to: Optional[str] = None
    attachments: list["AttachmentResponse"] = []
    ai_summary: Optional[str] = None
    ai_action_items: Optional[list] = None


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
    email_ids: list[int]
    action: str  # mark_read, mark_unread, star, unstar, archive, trash, spam, unspam, move
    label: Optional[str] = None


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
