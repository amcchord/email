import base64
import json
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.models.account import GoogleAccount
from backend.utils.security import decrypt_value, encrypt_value
from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GmailService:
    def __init__(self, account: GoogleAccount):
        self.account = account
        self._service = None

    def _get_credentials(self) -> Credentials:
        access_token = decrypt_value(self.account.encrypted_access_token)
        refresh_token = decrypt_value(self.account.encrypted_refresh_token)

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.labels",
            ],
        )
        return creds

    def _get_service(self):
        if self._service is None:
            creds = self._get_credentials()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    async def list_message_ids(self, page_token: Optional[str] = None, max_results: int = 500):
        """List message IDs with pagination."""
        service = self._get_service()
        kwargs = {
            "userId": "me",
            "maxResults": max_results,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = service.users().messages().list(**kwargs).execute()
            messages = result.get("messages", [])
            next_page = result.get("nextPageToken")
            total = result.get("resultSizeEstimate", 0)
            return messages, next_page, total
        except HttpError as e:
            logger.error(f"Gmail API error listing messages: {e}")
            raise

    async def get_message(self, message_id: str, format_type: str = "full"):
        """Get a single message."""
        service = self._get_service()
        try:
            return service.users().messages().get(
                userId="me",
                id=message_id,
                format=format_type,
            ).execute()
        except HttpError as e:
            logger.error(f"Gmail API error getting message {message_id}: {e}")
            raise

    async def batch_get_messages(self, message_ids: list[str], format_type: str = "full") -> list[dict]:
        """Batch get messages with rate limit handling."""
        import asyncio
        import time
        service = self._get_service()
        results = []

        batch_size = 20  # Conservative batch size to avoid rate limits
        for i in range(0, len(message_ids), batch_size):
            batch_ids = message_ids[i:i + batch_size]
            batch = service.new_batch_http_request()
            batch_results = {}
            retry_ids = []

            def make_callback(req_id):
                def callback(request_id, response, exception):
                    if exception:
                        status = getattr(exception, 'status_code', None) or getattr(getattr(exception, 'resp', None), 'status', 0)
                        if status in (429, 403):
                            retry_ids.append(req_id)
                        else:
                            logger.error(f"Batch get error for {req_id}: {exception}")
                        batch_results[req_id] = None
                    else:
                        batch_results[req_id] = response
                return callback

            for mid in batch_ids:
                batch.add(
                    service.users().messages().get(userId="me", id=mid, format=format_type),
                    request_id=mid,
                    callback=make_callback(mid),
                )

            batch.execute()
            results.extend([
                batch_results[mid] for mid in batch_ids
                if batch_results.get(mid) is not None
            ])

            # Retry rate-limited messages one at a time with delay
            for mid in retry_ids:
                await asyncio.sleep(1)
                try:
                    msg = service.users().messages().get(
                        userId="me", id=mid, format=format_type
                    ).execute()
                    results.append(msg)
                except HttpError as e:
                    if e.resp.status in (429, 403):
                        await asyncio.sleep(5)
                        try:
                            msg = service.users().messages().get(
                                userId="me", id=mid, format=format_type
                            ).execute()
                            results.append(msg)
                        except Exception:
                            logger.error(f"Retry failed for {mid}")
                    else:
                        logger.error(f"Get error for {mid}: {e}")

            # Pace between batches to stay under rate limits
            await asyncio.sleep(0.5)

        return results

    async def get_history(self, start_history_id: str, history_types: list[str] = None):
        """Get history of changes since a given history ID."""
        service = self._get_service()
        if history_types is None:
            history_types = ["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"]

        all_history = []
        page_token = None

        while True:
            kwargs = {
                "userId": "me",
                "startHistoryId": start_history_id,
                "historyTypes": history_types,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            try:
                result = service.users().history().list(**kwargs).execute()
                history = result.get("history", [])
                all_history.extend(history)
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            except HttpError as e:
                if e.resp.status == 404:
                    # History ID expired, need full sync
                    return None
                raise

        new_history_id = None
        if all_history:
            # The historyId of the last history record
            new_history_id = str(all_history[-1].get("id", start_history_id))

        return {"history": all_history, "new_history_id": new_history_id}

    async def list_labels(self):
        """List all labels for the account."""
        service = self._get_service()
        try:
            result = service.users().labels().list(userId="me").execute()
            return result.get("labels", [])
        except HttpError as e:
            logger.error(f"Gmail API error listing labels: {e}")
            raise

    async def modify_labels(self, message_id: str, add_labels: list[str] = None, remove_labels: list[str] = None):
        """Modify labels on a message."""
        service = self._get_service()
        body = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels
        try:
            return service.users().messages().modify(
                userId="me", id=message_id, body=body
            ).execute()
        except HttpError as e:
            logger.error(f"Gmail API error modifying message {message_id}: {e}")
            raise

    async def send_email(
        self,
        to: list[str],
        cc: list[str] = None,
        bcc: list[str] = None,
        subject: str = "",
        body_html: str = "",
        body_text: str = "",
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> str:
        """Send an email."""
        service = self._get_service()

        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg["Subject"] = subject
        msg["From"] = self.account.email

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id

        try:
            result = service.users().messages().send(userId="me", body=body).execute()
            return result.get("id", "")
        except HttpError as e:
            logger.error(f"Gmail API error sending email: {e}")
            raise

    async def create_draft(
        self,
        to: list[str],
        cc: list[str] = None,
        bcc: list[str] = None,
        subject: str = "",
        body_html: str = "",
        body_text: str = "",
        thread_id: Optional[str] = None,
    ) -> str:
        """Create a draft."""
        service = self._get_service()

        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg["Subject"] = subject
        msg["From"] = self.account.email

        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft_body = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        try:
            result = service.users().drafts().create(userId="me", body=draft_body).execute()
            return result.get("id", "")
        except HttpError as e:
            logger.error(f"Gmail API error creating draft: {e}")
            raise

    @staticmethod
    def parse_message(msg: dict) -> dict:
        """Parse a Gmail API message into a flat dict."""
        headers = {}
        payload = msg.get("payload", {})
        for header in payload.get("headers", []):
            name = header.get("name", "").lower()
            headers[name] = header.get("value", "")

        # Extract body
        body_text = ""
        body_html = ""

        def extract_parts(part):
            nonlocal body_text, body_html
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif mime == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    body_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            for sub_part in part.get("parts", []):
                extract_parts(sub_part)

        extract_parts(payload)

        # Extract attachments info
        attachments = []

        def extract_attachments(part):
            filename = part.get("filename", "")
            if filename:
                attachments.append({
                    "filename": filename,
                    "content_type": part.get("mimeType", ""),
                    "size_bytes": part.get("body", {}).get("size", 0),
                    "attachment_id": part.get("body", {}).get("attachmentId", ""),
                    "is_inline": bool(part.get("headers", []) and any(
                        h.get("name", "").lower() == "content-id"
                        for h in part.get("headers", [])
                    )),
                    "content_id": next(
                        (h.get("value", "") for h in part.get("headers", [])
                         if h.get("name", "").lower() == "content-id"),
                        None,
                    ),
                })
            for sub_part in part.get("parts", []):
                extract_attachments(sub_part)

        extract_attachments(payload)

        # Parse addresses
        from_addr = headers.get("from", "")
        from_name = ""
        if "<" in from_addr:
            parts = from_addr.split("<")
            from_name = parts[0].strip().strip('"')
            from_addr = parts[1].rstrip(">").strip()

        def parse_addr_list(raw):
            if not raw:
                return []
            result = []
            for part in raw.split(","):
                part = part.strip()
                if "<" in part:
                    parts = part.split("<")
                    name = parts[0].strip().strip('"')
                    addr = parts[1].rstrip(">").strip()
                    result.append({"name": name, "address": addr})
                else:
                    result.append({"name": "", "address": part})
            return result

        date_str = headers.get("date", "")
        email_date = None
        if date_str:
            from email.utils import parsedate_to_datetime
            try:
                email_date = parsedate_to_datetime(date_str)
                if email_date.tzinfo is None:
                    email_date = email_date.replace(tzinfo=timezone.utc)
            except Exception:
                try:
                    internal_date = msg.get("internalDate")
                    if internal_date:
                        email_date = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
                except Exception:
                    pass

        labels = msg.get("labelIds", [])
        is_read = "UNREAD" not in labels
        is_starred = "STARRED" in labels
        is_trash = "TRASH" in labels
        is_spam = "SPAM" in labels
        is_draft = "DRAFT" in labels
        is_sent = "SENT" in labels

        return {
            "gmail_message_id": msg.get("id", ""),
            "gmail_thread_id": msg.get("threadId", ""),
            "gmail_history_id": str(msg.get("historyId", "")),
            "subject": headers.get("subject", ""),
            "from_address": from_addr,
            "from_name": from_name,
            "to_addresses": parse_addr_list(headers.get("to", "")),
            "cc_addresses": parse_addr_list(headers.get("cc", "")),
            "bcc_addresses": parse_addr_list(headers.get("bcc", "")),
            "reply_to": headers.get("reply-to", ""),
            "date": email_date,
            "snippet": msg.get("snippet", ""),
            "body_text": body_text,
            "body_html": body_html,
            "labels": labels,
            "is_read": is_read,
            "is_starred": is_starred,
            "is_trash": is_trash,
            "is_spam": is_spam,
            "is_draft": is_draft,
            "is_sent": is_sent,
            "size_bytes": int(msg.get("sizeEstimate", 0)),
            "has_attachments": len(attachments) > 0,
            "message_id_header": headers.get("message-id", ""),
            "in_reply_to": headers.get("in-reply-to", ""),
            "references_header": headers.get("references", ""),
            "raw_headers": headers,
            "attachments": attachments,
        }
