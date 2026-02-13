import asyncio
import base64
import json
import logging
import random
import re
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
from backend.services.rate_limiter import gmail_rate_limiter, COST_DEFAULT, COST_GET

logger = logging.getLogger(__name__)
settings = get_settings()

# Gmail API quota: 250 units/second, ~15000/minute for reads.
# messages.list = 5 units, messages.get = 5 units, batch = 1 unit + per-item.
# Gmail batch requests support up to 100 items.
MAX_RETRIES = 8
BASE_BACKOFF = 5.0        # seconds
MAX_BACKOFF = 300.0       # seconds (5 min cap)
BATCH_INTERNAL_SIZE = 20  # messages per batch HTTP request
                          # Gmail limits ~15-25 concurrent requests per user;
                          # 50 consistently triggers "Too many concurrent requests".
BATCH_PAUSE = 0.5         # seconds between sub-batches
PAGE_PAUSE = 0.5          # seconds between list pages


def _is_rate_limit_error(error):
    """Check if an HttpError is a rate limit / quota error."""
    if not isinstance(error, HttpError):
        return False
    status = error.resp.status if hasattr(error, 'resp') else 0
    if status == 429:
        return True
    if status == 403:
        error_str = str(error).lower()
        if "quota" in error_str or "rate" in error_str or "limit" in error_str:
            return True
    return False


def _parse_retry_after(error) -> float:
    """Extract a delay in seconds from a Gmail 'Retry after <timestamp>' error.

    Returns 0 if we can't parse it, so the caller falls back to normal backoff.
    """
    error_str = str(error)
    # Look for ISO timestamp like "Retry after 2026-02-12T16:52:05.496Z"
    match = re.search(r'[Rr]etry\s+after\s+(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)', error_str)
    if match:
        try:
            retry_at = datetime.fromisoformat(match.group(1).replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            delay = (retry_at - now).total_seconds()
            if delay > 0:
                # Add a small buffer
                return min(delay + 2, MAX_BACKOFF)
        except Exception:
            pass
    # Also check for Retry-After header with seconds value
    if hasattr(error, 'resp') and hasattr(error.resp, 'get'):
        retry_header = error.resp.get('retry-after', '')
        if retry_header:
            try:
                return min(float(retry_header) + 1, MAX_BACKOFF)
            except ValueError:
                pass
    return 0


async def _rate_limit_sleep(error, attempt: int, context: str = ""):
    """Sleep respecting Retry-After if present, otherwise use exponential backoff."""
    # Try to parse the exact retry time from the error
    parsed_delay = _parse_retry_after(error)
    if parsed_delay > 0:
        logger.warning(f"Rate limited ({context}), server said wait {parsed_delay:.0f}s "
                       f"(attempt {attempt + 1}/{MAX_RETRIES})")
        await asyncio.sleep(parsed_delay)
    else:
        delay = min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 2), MAX_BACKOFF)
        logger.warning(f"Rate limited ({context}), backing off {delay:.1f}s "
                       f"(attempt {attempt + 1}/{MAX_RETRIES})")
        await asyncio.sleep(delay)


class GmailService:
    def __init__(self, account: GoogleAccount, client_id: str = None, client_secret: str = None):
        self.account = account
        self._service = None
        self._creds = None
        self._original_token = None
        # Use provided credentials, fall back to config
        self._client_id = client_id or settings.google_client_id
        self._client_secret = client_secret or settings.google_client_secret

    def _get_credentials(self) -> Credentials:
        access_token = decrypt_value(self.account.encrypted_access_token)
        refresh_token = decrypt_value(self.account.encrypted_refresh_token)

        self._original_token = access_token
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.labels",
            ],
        )
        self._creds = creds
        return creds

    def _get_service(self):
        if self._service is None:
            creds = self._get_credentials()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def get_refreshed_token(self) -> Optional[str]:
        """Return the new access token if it was refreshed, else None."""
        if self._creds is None:
            return None
        current_token = self._creds.token
        if current_token and current_token != self._original_token:
            return current_token
        return None

    async def _execute_with_retry(self, request_builder, context: str = "",
                                   max_retries: int = None, quota_cost: int = COST_DEFAULT):
        """Execute a Google API request with backoff that respects Retry-After.

        Acquires ``quota_cost`` tokens from the global rate limiter before
        each attempt so the project-wide quota ceiling is respected across
        all accounts.

        Runs the synchronous google-api-python-client execute() in a thread
        pool so it does not block the async event loop.
        """
        retries = max_retries if max_retries is not None else MAX_RETRIES
        loop = asyncio.get_event_loop()
        for attempt in range(retries):
            try:
                await gmail_rate_limiter.acquire(quota_cost)
                return await loop.run_in_executor(None, request_builder.execute)
            except HttpError as e:
                if _is_rate_limit_error(e) and attempt < retries - 1:
                    # Drain the bucket so other concurrent callers also pause
                    gmail_rate_limiter.drain()
                    await _rate_limit_sleep(e, attempt, context)
                    continue
                raise

    async def list_message_ids(self, page_token: Optional[str] = None, max_results: int = 100):
        """List message IDs with pagination. Small page size to stay under quota."""
        service = self._get_service()
        kwargs = {
            "userId": "me",
            "maxResults": max_results,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        result = await self._execute_with_retry(
            service.users().messages().list(**kwargs),
            context="list_message_ids",
        )
        messages = result.get("messages", [])
        next_page = result.get("nextPageToken")
        total = result.get("resultSizeEstimate", 0)
        return messages, next_page, total

    async def get_message(self, message_id: str, format_type: str = "full"):
        """Get a single message."""
        service = self._get_service()
        return await self._execute_with_retry(
            service.users().messages().get(userId="me", id=message_id, format=format_type),
            context=f"get_message({message_id})",
        )

    async def batch_get_messages(self, message_ids: list[str], format_type: str = "full") -> list[dict]:
        """Batch get messages with rate limit handling and Retry-After support.

        When individual items inside a batch are rate-limited, they are
        skipped rather than retried one-by-one (which would amplify quota
        usage).  The next sync tick will pick them up via history.

        If rate limiting is severe (>= 50% of items in a sub-batch, or 3+
        consecutive sub-batches with any rate-limited items), raises the
        underlying HttpError so the caller can abort early instead of
        consuming quota for minutes while making minimal progress.
        """
        service = self._get_service()
        loop = asyncio.get_event_loop()
        results = []
        consecutive_rl_batches = 0

        for i in range(0, len(message_ids), BATCH_INTERNAL_SIZE):
            batch_ids = message_ids[i:i + BATCH_INTERNAL_SIZE]

            # Acquire tokens for the whole sub-batch up front
            # (1 unit for the batch request + COST_GET per item)
            batch_cost = 1 + COST_GET * len(batch_ids)
            await gmail_rate_limiter.acquire(batch_cost)

            # Try the batch with retries
            for attempt in range(MAX_RETRIES):
                batch = service.new_batch_http_request()
                batch_results = {}
                rate_limited_ids = []
                last_rate_error = None

                def make_callback(req_id):
                    def callback(request_id, response, exception):
                        nonlocal last_rate_error
                        if exception:
                            if _is_rate_limit_error(exception):
                                rate_limited_ids.append(req_id)
                                last_rate_error = exception
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

                try:
                    await loop.run_in_executor(None, batch.execute)
                except HttpError as e:
                    # Entire batch rejected (e.g. quota at the HTTP level)
                    if _is_rate_limit_error(e) and attempt < MAX_RETRIES - 1:
                        gmail_rate_limiter.drain()
                        await _rate_limit_sleep(e, attempt, "batch_execute")
                        continue
                    raise

                # Collect successful results
                results.extend([
                    batch_results[mid] for mid in batch_ids
                    if batch_results.get(mid) is not None
                ])

                # If some individual items were rate-limited, check severity
                if rate_limited_ids:
                    gmail_rate_limiter.drain()
                    consecutive_rl_batches += 1
                    rl_ratio = len(rate_limited_ids) / len(batch_ids)

                    # Abort if rate limiting is severe: either most items
                    # in this batch failed, or we've had 3+ consecutive
                    # sub-batches with any rate-limited items.  Continuing
                    # would burn quota for minutes with minimal progress.
                    if rl_ratio >= 0.5 or consecutive_rl_batches >= 3:
                        logger.warning(
                            f"Batch: {len(rate_limited_ids)} of {len(batch_ids)} items "
                            f"rate-limited (consecutive={consecutive_rl_batches}) "
                            f"-- aborting to preserve quota ({len(results)} msgs fetched so far)"
                        )
                        if last_rate_error:
                            raise last_rate_error
                        raise HttpError(
                            resp=type('obj', (object,), {'status': 429})(),
                            content=b'Rate limited: too many batch items failed',
                        )

                    logger.warning(
                        f"Batch: {len(rate_limited_ids)} of {len(batch_ids)} items "
                        f"rate-limited -- skipping (will retry next sync)"
                    )
                else:
                    # Reset consecutive counter on a clean batch
                    consecutive_rl_batches = 0

                # Done with this sub-batch (success or partial)
                break

            # Pace between sub-batches
            await asyncio.sleep(BATCH_PAUSE)

        return results

    async def get_history(self, start_history_id: str, history_types: list[str] = None,
                          max_retries: int = 2):
        """Get history of changes since a given history ID.

        Uses few retries by default -- incremental syncs should fail fast
        and let the next cron tick retry rather than blocking the worker.
        """
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
                result = await self._execute_with_retry(
                    service.users().history().list(**kwargs),
                    context="get_history",
                    max_retries=max_retries,
                )
                history = result.get("history", [])
                all_history.extend(history)
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
                await asyncio.sleep(PAGE_PAUSE)
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
        result = await self._execute_with_retry(
            service.users().labels().list(userId="me"),
            context="list_labels",
        )
        return result.get("labels", [])

    async def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download an attachment and return its raw bytes."""
        import base64
        service = self._get_service()
        result = await self._execute_with_retry(
            service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id,
            ),
            context=f"get_attachment({message_id}, {attachment_id})",
        )
        data = result.get("data", "")
        return base64.urlsafe_b64decode(data)

    async def modify_labels(self, message_id: str, add_labels: list[str] = None, remove_labels: list[str] = None):
        """Modify labels on a message."""
        service = self._get_service()
        body = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels
        return await self._execute_with_retry(
            service.users().messages().modify(userId="me", id=message_id, body=body),
            context=f"modify_labels({message_id})",
        )

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

        request = service.users().messages().send(userId="me", body=body)
        result = await self._execute_with_retry(request, context="send_email")
        return result.get("id", "")

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

        request = service.users().drafts().create(userId="me", body=draft_body)
        result = await self._execute_with_retry(request, context="create_draft")
        return result.get("id", "")

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
