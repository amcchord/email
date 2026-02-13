"""
Chat service: three-phase Plan-Execute-Verify agent for answering
natural-language questions about a user's emails.

Tasks within the execute phase run in parallel when they have no
dependencies on each other (DAG-based wave execution).
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncGenerator, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, or_
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.database import async_session as make_session
from backend.models.email import Email, Attachment
from backend.models.account import GoogleAccount
from backend.models.user import User
from backend.schemas.auth import DEFAULT_AI_PREFERENCES

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_TOOL_ROUNDS_PER_TASK = 10
MAX_TASKS = 7

# ---------------------------------------------------------------------------
# Tool definitions (JSON schema for Claude tool_use)
# ---------------------------------------------------------------------------

SEARCH_EMAILS_TOOL = {
    "name": "search_emails",
    "description": (
        "Search the user's emails using full-text search. "
        "Returns id, subject, from_address, from_name, date, and snippet for each match. "
        "Use date_from/date_to (YYYY-MM-DD) to filter by date range. "
        "Use from_address to filter by sender email (substring match). "
        "Results are ranked by relevance."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (full-text search terms)",
            },
            "date_from": {
                "type": "string",
                "description": "Start date filter (YYYY-MM-DD), inclusive. Optional.",
            },
            "date_to": {
                "type": "string",
                "description": "End date filter (YYYY-MM-DD), inclusive. Optional.",
            },
            "from_address": {
                "type": "string",
                "description": "Filter by sender email address (substring match). Optional.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 20, max 50).",
            },
        },
        "required": ["query"],
    },
}

READ_EMAIL_TOOL = {
    "name": "read_email",
    "description": (
        "Read the full content of a single email by its ID. "
        "Returns subject, from, to, cc, date, body_text (up to 8000 chars), "
        "and a list of attachment filenames."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "integer",
                "description": "The email ID to read.",
            },
        },
        "required": ["email_id"],
    },
}

READ_EMAILS_BATCH_TOOL = {
    "name": "read_emails_batch",
    "description": (
        "Read the full content of up to 10 emails at once by their IDs. "
        "More efficient than calling read_email multiple times."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "email_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of email IDs to read (max 10).",
            },
        },
        "required": ["email_ids"],
    },
}

LIST_SENDER_DOMAINS_TOOL = {
    "name": "list_sender_domains",
    "description": (
        "List unique sender domains from the user's emails, ranked by email count. "
        "Optionally filter by date range and by subject keywords (e.g. 'order', 'shipped', 'receipt'). "
        "This is very useful for discovering WHICH companies/retailers sent emails in a period, "
        "especially for questions about orders, purchases, subscriptions, etc. "
        "You can then use the domains to search for specific emails from those senders."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_from": {
                "type": "string",
                "description": "Start date filter (YYYY-MM-DD). Optional.",
            },
            "date_to": {
                "type": "string",
                "description": "End date filter (YYYY-MM-DD). Optional.",
            },
            "subject_contains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Filter to emails whose subject contains ANY of these keywords "
                    "(case-insensitive). e.g. ['order', 'shipped', 'delivery', 'receipt', 'confirmation', 'invoice']. "
                    "Optional -- omit to see all sender domains."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max domains to return (default 50).",
            },
        },
        "required": [],
    },
}

READ_ATTACHMENT_TOOL = {
    "name": "read_attachment",
    "description": (
        "Read an email attachment. For PDFs, converts each page to an image "
        "so you can see and extract the content. For image attachments, returns "
        "the image directly. Use this when an email body is empty and details "
        "are in an attached PDF or image (e.g. receipts, invoices, order confirmations)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "integer",
                "description": "The email ID that has the attachment.",
            },
            "attachment_filename": {
                "type": "string",
                "description": "The filename of the attachment to read.",
            },
        },
        "required": ["email_id", "attachment_filename"],
    },
}

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for information, images, or product details. "
        "Returns title, URL, snippet, and thumbnail URL for top results. "
        "Useful for finding product images, verifying vendors, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
        },
        "required": ["query"],
    },
}

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

PLAN_SYSTEM_PROMPT = """You are a research planner for an email assistant. The user will ask a question about their emails. Your job is EITHER to break it into a structured research plan OR to ask the user a clarifying question if the request is too vague or ambiguous.

IMPORTANT: If the question is unclear, too broad, or you're unsure what the user wants, ASK for clarification instead of guessing. It is MUCH better to ask a quick question than to run a 5-minute search in the wrong direction. Examples of when to ask:
- "Find my emails" -- too vague, ask what they're looking for
- "What did I buy?" -- ask for a time period, category, or retailer
- "Tell me about that thing" -- ask what thing they mean
- Ambiguous pronouns or references with no context

However, do NOT ask if the question is reasonably clear -- even if imperfect. A question like "What furniture did I order in 2020?" is clear enough to plan for.

RESPONSE FORMAT -- respond with ONLY a JSON object, one of two forms:

Form 1 -- Clarification needed:
{
  "clarification": "Your question to the user here. Be specific about what you need to know."
}

Form 2 -- Research plan:
{
  "tasks": [
    {"id": 1, "description": "...", "search_strategy": "...", "depends_on": []},
    ...
  ]
}

Each task in the plan must have:
- "id": sequential integer starting at 1
- "description": what to do in this step
- "search_strategy": how to approach this using the available tools
- "depends_on": array of task IDs this task depends on (empty array [] if it can run immediately)

Tasks with no dependencies (depends_on: []) run IN PARALLEL. Tasks that depend on others wait until those complete.

AVAILABLE TOOLS (for your reference when planning):
- list_sender_domains: List unique sender domains with email counts, filtered by date and subject keywords. EXTREMELY useful as a first step for order/purchase/subscription questions.
- search_emails: Full-text search with date/sender filters.
- read_email / read_emails_batch: Read full email content.
- read_attachment: Read PDF/image attachments (converts PDFs to images for visual inspection).
- web_search: Search the web for images, product details, etc. (if configured).

STRATEGY for order/purchase/delivery questions:
1. FIRST task (depends_on: []): Use list_sender_domains with subject keywords like ['order', 'shipped', 'delivery', 'receipt', 'confirmation'] to discover which companies sent transactional emails.
2. IN PARALLEL (depends_on: []): Search for the specific address/location mentioned in the query.
3. NEXT (depends_on: [1]): From the domain list, identify relevant retailers/vendors and search for their emails.
4. THEN (depends_on: [2, 3]): Read and cross-reference emails to verify details.
5. FINALLY: Web search for images or supplementary info if needed.

When the user asks about a specific time period, also search slightly beyond (a few months after) to catch delayed confirmations. Extend the date range in your date filters."""

EXECUTE_SYSTEM_PROMPT = """You are a research assistant working through a specific task from a research plan about a user's emails.

You have access to tools to list sender domains, search emails, read email content, read attachments, and search the web. Use them to complete your assigned task.

CRITICAL GUIDELINES:
- You have a LIMITED number of tool calls (about 10). Be STRATEGIC, not exhaustive.
- Start with 1-2 broad searches, then read the most promising results. Do NOT search dozens of times.
- After 3-5 tool calls, you should have enough data. STOP searching and SUMMARIZE what you found.
- Read emails fully before drawing conclusions -- snippets can be misleading.
- For date-based queries, use the date_from and date_to parameters. But also search slightly beyond the requested period to catch follow-up emails.
- When looking for orders from a specific retailer, search for the retailer name WITHOUT combining it with an address -- the address may only appear in certain emails.
- When searching by sender domain (from_address), use just the base domain (e.g. "crateandbarrel" not "mail.crateandbarrel.com") to catch ALL emails from that company -- they often use multiple subdomains (e.g. mail.*, narvar.*, customer_service@*).
- IMPORTANT: When investigating a specific retailer, do a BROAD first search: use a simple generic query like "order" with from_address filter and a high limit (30-50). This catches receipts, confirmations, shipment notices, etc. Do NOT combine too many keywords in one search -- you will miss emails whose subject uses different words (e.g. "receipt" vs "confirmation" vs "shipped").
- If a search returns no results, try ONE alternative query then move on.
- It is MUCH better to summarize partial findings than to keep searching and run out of tool calls.
- If an email body is empty or sparse but has attachments (especially PDFs), use read_attachment to examine them -- invoices, receipts, and order details are often in PDF attachments.

When you have gathered enough information (or used 3-5 tool calls), STOP making tool calls and respond with a clear factual summary of what you found, including:
- Specific email IDs
- Key details (product names, dates, senders, addresses, etc.)
- What you could NOT find (so later tasks know what gaps remain)

Do NOT produce markdown -- just a factual summary."""

VERIFY_SYSTEM_PROMPT = """You are a research reviewer and writer for an email assistant. You will receive:
1. The user's original question
2. A research plan that was executed
3. The results from each task in the plan

Your job is to:
1. Review all findings against the original question
2. Check for gaps -- is anything missing or incomplete?
3. Produce a comprehensive, well-formatted markdown answer

Output format:
- Use rich markdown with headers, tables, bullet points, and images where appropriate.
- If product/item images were found via web search, include them as ![description](url).
- IMPORTANT: Do NOT guess or fabricate image URLs. Only include image URLs that were explicitly found in the research results (from web_search results or email content). Made-up URLs will be broken. If no image URL was found for an item, simply omit the image.
- Cite specific emails when relevant (mention subject, sender, date).
- If information was incomplete or not found, include a "Notes" section explaining what was missing.
- Be thorough but concise. Structure the answer clearly.
- Use tables for lists of items with multiple attributes (name, price, vendor, etc.).

Respond with ONLY the markdown answer."""


# ---------------------------------------------------------------------------
# HTML-to-text extraction for HTML-only emails
# ---------------------------------------------------------------------------

def _extract_text_from_html(html: str, max_chars: int = 8000) -> str:
    """Extract readable text from HTML email content.

    Handles retailer emails (CB2, Crate & Barrel, etc.) that have
    body_html but no body_text.  Strips CSS, invisible characters,
    and deduplicates lines.
    """
    import re

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        # Remove non-content elements
        for tag in soup(["script", "style", "head", "meta", "link", "noscript"]):
            tag.decompose()

        # Remove hidden elements
        for tag in list(soup.find_all(style=True)):
            try:
                style_val = (tag.get("style") or "").lower()
                if "display:none" in style_val or "display: none" in style_val:
                    tag.decompose()
            except (AttributeError, TypeError):
                continue

        # Get full text, then clean up
        raw_text = soup.get_text(separator="\n", strip=True)

        # Remove zero-width and invisible Unicode characters
        raw_text = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u2060\u00ad]+", "", raw_text)
        # Clean up HTML entities that leak through
        raw_text = raw_text.replace("&zwnj;", "").replace("&nbsp;", " ")
        raw_text = raw_text.replace("\xa0", " ")  # non-breaking space
        # Decode numeric HTML entities
        raw_text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), raw_text)
        raw_text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), raw_text)
        # Collapse excessive whitespace / blank lines
        raw_text = re.sub(r"[ \t]+", " ", raw_text)
        raw_text = re.sub(r"\n[ \t]*\n[\n ]*", "\n\n", raw_text)

        # Filter out lines that are just CSS or very short noise
        clean_lines = []
        for line in raw_text.split("\n"):
            stripped = line.strip()
            # Skip CSS fragments, @media rules, font-face declarations
            if stripped.startswith("@media") or stripped.startswith("@font-face"):
                continue
            if stripped.startswith(".") and "{" in stripped:
                continue
            if stripped.endswith("{") or stripped.endswith("}"):
                continue
            if stripped.startswith("font-") or stripped.startswith("color:"):
                continue
            # Skip very short meaningless lines
            if len(stripped) < 2:
                continue
            clean_lines.append(stripped)

        # Deduplicate consecutive identical lines
        deduped = []
        for line in clean_lines:
            if not deduped or line != deduped[-1]:
                deduped.append(line)

        result = "\n".join(deduped)

        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (truncated)"

        return result

    except Exception as e:
        logger.warning(f"HTML extraction failed ({type(e).__name__}): {e}")
        # Fallback: strip style/script blocks, then tags
        text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[\u200b\u200c\u200d\ufeff]+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text


def _get_email_body(email_obj) -> str:
    """Get the best available body text from an email.

    Prefers body_text; falls back to extracting text from body_html.
    """
    body = email_obj.body_text or ""
    # If body_text is empty/trivial but HTML exists, extract from HTML
    if len(body.strip()) < 50 and email_obj.body_html:
        html_text = _extract_text_from_html(email_obj.body_html)
        if len(html_text) > len(body):
            body = html_text
    if len(body) > 8000:
        body = body[:8000] + "\n... (truncated)"
    return body


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _execute_list_sender_domains(
    params: dict, account_ids: list[int], db: AsyncSession,
) -> str:
    """Execute the list_sender_domains tool."""
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    subject_keywords = params.get("subject_contains", [])
    limit = min(params.get("limit", 50), 100)

    domain_expr = func.split_part(Email.from_address, '@', 2)

    q = select(
        domain_expr.label("domain"),
        func.count().label("cnt"),
    ).where(
        Email.account_id.in_(account_ids),
        Email.is_trash == False,
        Email.is_spam == False,
    )

    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.where(Email.date >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d")
            dt = dt.replace(hour=23, minute=59, second=59)
            q = q.where(Email.date <= dt)
        except ValueError:
            pass

    if subject_keywords:
        conditions = []
        for kw in subject_keywords:
            conditions.append(Email.subject.ilike(f"%{kw}%"))
        q = q.where(or_(*conditions))

    q = q.group_by("domain").order_by(func.count().desc()).limit(limit)

    result = await db.execute(q)
    rows = result.all()

    domains = []
    for domain, cnt in rows:
        if domain:
            domains.append({"domain": domain, "email_count": cnt})

    return json.dumps({
        "domains": domains,
        "total": len(domains),
        "note": "Use from_address filter in search_emails to find emails from a specific domain.",
    })


async def _execute_search_emails(
    params: dict, account_ids: list[int], db: AsyncSession,
) -> str:
    """Execute the search_emails tool."""
    query_text = params.get("query", "")
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    from_address = params.get("from_address")
    limit = min(params.get("limit", 20), 50)

    ts_query = func.plainto_tsquery("english", query_text)

    q = select(Email).where(
        Email.account_id.in_(account_ids),
        Email.is_trash == False,
        Email.is_spam == False,
    )

    # Full-text search OR ilike fallback
    search_pattern = f"%{query_text}%"
    q = q.where(
        or_(
            Email.search_vector.op("@@")(ts_query),
            Email.subject.ilike(search_pattern),
            Email.from_address.ilike(search_pattern),
            Email.body_text.ilike(search_pattern),
        )
    )

    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.where(Email.date >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d")
            dt = dt.replace(hour=23, minute=59, second=59)
            q = q.where(Email.date <= dt)
        except ValueError:
            pass

    if from_address:
        q = q.where(Email.from_address.ilike(f"%{from_address}%"))

    rank = func.ts_rank(Email.search_vector, ts_query)
    q = q.order_by(desc(rank)).limit(limit)

    result = await db.execute(q)
    emails = result.scalars().all()

    if not emails:
        return json.dumps({"results": [], "total": 0, "message": "No emails found matching the search."})

    results = []
    for e in emails:
        results.append({
            "id": e.id,
            "subject": e.subject or "(no subject)",
            "from_address": e.from_address,
            "from_name": e.from_name,
            "date": e.date.isoformat() if e.date else None,
            "snippet": (e.snippet or "")[:200],
        })

    return json.dumps({"results": results, "total": len(results)})


async def _execute_read_email(
    params: dict, account_ids: list[int], db: AsyncSession,
) -> str:
    """Execute the read_email tool."""
    email_id = params.get("email_id")
    if not email_id:
        return json.dumps({"error": "email_id is required"})

    result = await db.execute(
        select(Email)
        .options(selectinload(Email.attachments))
        .where(Email.id == email_id, Email.account_id.in_(account_ids))
    )
    email = result.scalar_one_or_none()

    if not email:
        return json.dumps({"error": f"Email {email_id} not found or not accessible"})

    body = _get_email_body(email)

    attachments = []
    for att in email.attachments:
        attachments.append({
            "filename": att.filename,
            "content_type": att.content_type,
            "size_bytes": att.size_bytes,
        })

    return json.dumps({
        "id": email.id,
        "subject": email.subject or "(no subject)",
        "from_address": email.from_address,
        "from_name": email.from_name,
        "to_addresses": email.to_addresses or [],
        "cc_addresses": email.cc_addresses or [],
        "date": email.date.isoformat() if email.date else None,
        "body_text": body,
        "attachments": attachments,
        "labels": email.labels or [],
    })


async def _execute_read_emails_batch(
    params: dict, account_ids: list[int], db: AsyncSession,
) -> str:
    """Execute the read_emails_batch tool."""
    email_ids = params.get("email_ids", [])
    if not email_ids:
        return json.dumps({"error": "email_ids is required"})
    email_ids = email_ids[:10]

    result = await db.execute(
        select(Email)
        .options(selectinload(Email.attachments))
        .where(Email.id.in_(email_ids), Email.account_id.in_(account_ids))
    )
    emails = result.scalars().all()

    results = []
    for email in emails:
        body = _get_email_body(email)

        attachments = []
        for att in email.attachments:
            attachments.append({
                "filename": att.filename,
                "content_type": att.content_type,
                "size_bytes": att.size_bytes,
            })

        results.append({
            "id": email.id,
            "subject": email.subject or "(no subject)",
            "from_address": email.from_address,
            "from_name": email.from_name,
            "to_addresses": email.to_addresses or [],
            "cc_addresses": email.cc_addresses or [],
            "date": email.date.isoformat() if email.date else None,
            "body_text": body,
            "attachments": attachments,
            "labels": email.labels or [],
        })

    return json.dumps({"emails": results, "count": len(results)})


async def _execute_read_attachment(
    params: dict, account_ids: list[int], db: AsyncSession,
) -> list:
    """Execute the read_attachment tool. Returns a list of content blocks (text + images)."""
    import base64

    email_id = params.get("email_id")
    target_filename = params.get("attachment_filename", "")

    if not email_id or not target_filename:
        return [{"type": "text", "text": json.dumps({"error": "email_id and attachment_filename are required"})}]

    result = await db.execute(
        select(Email)
        .options(selectinload(Email.attachments))
        .where(Email.id == email_id, Email.account_id.in_(account_ids))
    )
    email = result.scalar_one_or_none()
    if not email:
        return [{"type": "text", "text": json.dumps({"error": f"Email {email_id} not found"})}]

    # Find the matching attachment (exact then fuzzy)
    target_att = None
    for att in email.attachments:
        if att.filename and att.filename.lower() == target_filename.lower():
            target_att = att
            break
    if not target_att:
        for att in email.attachments:
            if att.filename and target_filename.lower() in att.filename.lower():
                target_att = att
                break

    if not target_att:
        available = [a.filename for a in email.attachments if a.filename]
        return [{"type": "text", "text": json.dumps({
            "error": f"Attachment '{target_filename}' not found",
            "available_attachments": available,
        })}]

    if not target_att.gmail_attachment_id:
        return [{"type": "text", "text": json.dumps({"error": "Attachment has no Gmail ID (may be inline)"})}]

    # --- Attachment cache: read from disk if already downloaded ---
    import os
    raw_bytes = None

    if target_att.storage_path and os.path.isfile(target_att.storage_path):
        try:
            with open(target_att.storage_path, "rb") as f:
                raw_bytes = f.read()
            logger.info(f"Attachment cache hit: {target_att.storage_path}")
        except Exception as e:
            logger.warning(f"Cache read failed, will re-download: {e}")
            raw_bytes = None

    # --- Cache miss: download from Gmail API ---
    if raw_bytes is None:
        try:
            account = await db.execute(
                select(GoogleAccount).where(GoogleAccount.id == email.account_id)
            )
            account_obj = account.scalar_one_or_none()
            if not account_obj:
                return [{"type": "text", "text": json.dumps({"error": "Account not found"})}]

            from backend.services.gmail import GmailService
            from backend.services.credentials import get_google_credentials
            client_id, client_secret = await get_google_credentials(db)
            gmail = GmailService(account_obj, client_id=client_id, client_secret=client_secret)
            raw_bytes = await gmail.get_attachment(email.gmail_message_id, target_att.gmail_attachment_id)

            # Save to disk cache
            try:
                cache_dir = os.path.join(
                    settings.attachment_storage_path,
                    str(email.account_id),
                    str(email.id),
                )
                os.makedirs(cache_dir, exist_ok=True)
                safe_name = target_att.filename.replace("/", "_").replace("\\", "_")
                cache_path = os.path.join(cache_dir, safe_name)
                with open(cache_path, "wb") as f:
                    f.write(raw_bytes)
                # Update DB so future calls skip the API entirely
                target_att.storage_path = cache_path
                await db.commit()
                logger.info(f"Attachment cached to {cache_path}")
            except Exception as cache_err:
                logger.warning(f"Failed to cache attachment to disk: {cache_err}")

        except Exception as e:
            logger.error(f"Failed to download attachment: {e}")
            return [{"type": "text", "text": json.dumps({"error": f"Failed to download attachment: {str(e)}"})}]

    content_type = (target_att.content_type or "").lower()
    content_blocks = []

    # Handle PDFs
    if "pdf" in content_type or target_filename.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            num_pages = min(len(doc), 5)

            content_blocks.append({
                "type": "text",
                "text": f"PDF attachment '{target_filename}' has {len(doc)} pages. Showing {num_pages} page(s):",
            })

            for page_num in range(num_pages):
                page = doc[page_num]
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("jpeg")
                b64_data = base64.standard_b64encode(img_bytes).decode("utf-8")

                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64_data,
                    },
                })

            doc.close()

        except Exception as e:
            logger.error(f"PDF conversion failed: {e}")
            content_blocks = [{"type": "text", "text": json.dumps({
                "error": f"Failed to convert PDF to images: {str(e)}"
            })}]

    # Handle images directly
    elif content_type.startswith("image/"):
        media_type = "image/jpeg"
        if "png" in content_type:
            media_type = "image/png"
        elif "gif" in content_type:
            media_type = "image/gif"
        elif "webp" in content_type:
            media_type = "image/webp"

        b64_data = base64.standard_b64encode(raw_bytes).decode("utf-8")
        content_blocks = [
            {"type": "text", "text": f"Image attachment '{target_filename}':"},
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64_data}},
        ]

    else:
        content_blocks = [{"type": "text", "text": json.dumps({
            "message": f"Attachment '{target_filename}' is type '{content_type}' which cannot be visually rendered.",
            "size_bytes": target_att.size_bytes,
        })}]

    return content_blocks


async def _execute_web_search(params: dict) -> str:
    """Execute the web_search tool using Brave Search API."""
    query = params.get("query", "")
    api_key = settings.brave_search_api_key
    if not api_key:
        return json.dumps({"error": "Web search is not configured (no Brave Search API key)."})

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 10},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:10]:
            result = {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            }
            thumbnail = item.get("thumbnail", {})
            if thumbnail and thumbnail.get("src"):
                result["image_url"] = thumbnail["src"]
            results.append(result)

        return json.dumps({"results": results, "total": len(results)})

    except Exception as e:
        logger.error(f"Web search error: {e}")
        return json.dumps({"error": f"Web search failed: {str(e)}"})


async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    account_ids: list[int],
    db: AsyncSession,
):
    """Route a tool call to its handler. Returns str or list of content blocks."""
    if tool_name == "list_sender_domains":
        return await _execute_list_sender_domains(tool_input, account_ids, db)
    elif tool_name == "search_emails":
        return await _execute_search_emails(tool_input, account_ids, db)
    elif tool_name == "read_email":
        return await _execute_read_email(tool_input, account_ids, db)
    elif tool_name == "read_emails_batch":
        return await _execute_read_emails_batch(tool_input, account_ids, db)
    elif tool_name == "read_attachment":
        return await _execute_read_attachment(tool_input, account_ids, db)
    elif tool_name == "web_search":
        return await _execute_web_search(tool_input)
    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _tool_progress_detail(tool_name: str, tool_input: dict) -> str:
    if tool_name == "list_sender_domains":
        keywords = tool_input.get("subject_contains", [])
        if keywords:
            return f"Listing sender domains (filtering by: {', '.join(keywords)})"
        return "Listing sender domains"
    elif tool_name == "search_emails":
        query = tool_input.get("query", "")
        parts = [f"Searching emails for '{query}'"]
        if tool_input.get("date_from") or tool_input.get("date_to"):
            parts.append(f"({tool_input.get('date_from', '...')} to {tool_input.get('date_to', '...')})")
        if tool_input.get("from_address"):
            parts.append(f"from {tool_input['from_address']}")
        return " ".join(parts)
    elif tool_name == "read_email":
        return f"Reading email #{tool_input.get('email_id', '?')}"
    elif tool_name == "read_emails_batch":
        return f"Reading {len(tool_input.get('email_ids', []))} emails"
    elif tool_name == "read_attachment":
        return f"Reading attachment '{tool_input.get('attachment_filename', '?')}' from email #{tool_input.get('email_id', '?')}"
    elif tool_name == "web_search":
        return f"Searching the web for '{tool_input.get('query', '')}'"
    return f"Running {tool_name}"


def _compute_waves(tasks: list[dict]) -> list[list[dict]]:
    """Given tasks with depends_on, group into execution waves.

    Wave 0: tasks with no deps. Wave 1: tasks whose deps are all in wave 0, etc.
    """
    task_map = {t["id"]: t for t in tasks}
    assigned = {}  # task_id -> wave_number
    waves = []

    for _ in range(len(tasks) + 1):  # safety bound
        wave = []
        for t in tasks:
            if t["id"] in assigned:
                continue
            deps = t.get("depends_on", [])
            if all(d in assigned for d in deps):
                wave.append(t)
        if not wave:
            break
        wave_num = len(waves)
        for t in wave:
            assigned[t["id"]] = wave_num
        waves.append(wave)

    # Catch any un-assigned tasks (circular deps fallback)
    remaining = [t for t in tasks if t["id"] not in assigned]
    if remaining:
        waves.append(remaining)

    return waves


# ---------------------------------------------------------------------------
# Image URL validation -- check markdown images return 200
# ---------------------------------------------------------------------------

async def _validate_markdown_images(markdown: str) -> str:
    """Check all ![alt](url) image URLs in the markdown.

    Removes images that return non-200 status and replaces them with
    a text note. Checks are done concurrently with a short timeout.
    """
    import re

    img_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    matches = list(img_pattern.finditer(markdown))

    if not matches:
        return markdown

    # Check all URLs concurrently
    async def check_url(url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as http:
                resp = await http.head(url)
                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "image" in content_type or "octet-stream" in content_type:
                        return True
                # Some servers don't support HEAD, try GET with range
                if resp.status_code in (405, 403):
                    resp2 = await http.get(url, headers={"Range": "bytes=0-0"})
                    if resp2.status_code in (200, 206):
                        return True
                return False
        except Exception:
            return False

    # Gather all checks
    urls = [m.group(2) for m in matches]
    unique_urls = list(dict.fromkeys(urls))  # dedupe preserving order
    results = await asyncio.gather(*[check_url(u) for u in unique_urls])
    url_valid = dict(zip(unique_urls, results))

    logger.info(f"Image URL validation: {sum(url_valid.values())}/{len(url_valid)} valid")

    # Replace broken images
    def replace_image(match):
        alt = match.group(1)
        url = match.group(2)
        if url_valid.get(url, False):
            return match.group(0)  # keep valid images
        # Replace with a note
        if alt:
            return f"*[Image not available: {alt}]*"
        return ""

    return img_pattern.sub(replace_image, markdown)


# ---------------------------------------------------------------------------
# Single-task executor (runs in its own DB session)
# ---------------------------------------------------------------------------

async def _run_single_task(
    task: dict,
    user_query: str,
    all_tasks: list[dict],
    prior_results: dict,
    account_ids: list[int],
    execute_model: str,
    tools: list[dict],
    event_queue: asyncio.Queue,
):
    """Execute one task's tool loop. Pushes SSE events onto event_queue.

    Returns (task_id, summary_text, tokens_used).
    Uses its own DB session so it can run concurrently with other tasks.
    """
    import anthropic

    task_id = task["id"]
    task_desc = task.get("description", "")
    tokens_used = 0

    await event_queue.put(_sse_event("task_start", {"task_id": task_id, "description": task_desc}))

    # Build context from prior tasks this one depends on
    deps = task.get("depends_on", [])
    prior_context = ""
    for dep_id in deps:
        if dep_id in prior_results:
            prior_context += f"\n--- Results from Task {dep_id} ---\n{prior_results[dep_id]}\n"

    task_user_message = (
        f"Original question: {user_query}\n\n"
        f"Full plan:\n{json.dumps(all_tasks, indent=2)}\n\n"
    )
    if prior_context:
        task_user_message += f"Results from prior tasks:{prior_context}\n\n"
    task_user_message += (
        f"Your current task (Task {task_id}): {task_desc}\n"
        f"Strategy: {task.get('search_strategy', '')}\n\n"
        f"Complete this task using the tools available. When done, summarize your findings."
    )

    task_messages = [{"role": "user", "content": task_user_message}]

    client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

    async with make_session() as db:
        task_completed = False
        for _round in range(MAX_TOOL_ROUNDS_PER_TASK):
            try:
                response = await client.messages.create(
                    model=execute_model,
                    max_tokens=8192,
                    system=EXECUTE_SYSTEM_PROMPT,
                    tools=tools,
                    messages=task_messages,
                )
                tokens_used += response.usage.input_tokens + response.usage.output_tokens
            except Exception as e:
                logger.error(f"Execute phase error for task {task_id}: {e}")
                await event_queue.put(_sse_event("task_failed", {"task_id": task_id, "error": str(e)}))
                return task_id, f"Task failed: {str(e)}", tokens_used

            # Done?
            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                summary = "\n".join(text_parts) if text_parts else "No findings."
                await event_queue.put(_sse_event("task_complete", {
                    "task_id": task_id,
                    "summary": summary[:500],
                }))
                task_completed = True
                return task_id, summary, tokens_used

            # Process tool calls
            assistant_content = []
            tool_results = []

            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

                    detail = _tool_progress_detail(block.name, block.input)
                    await event_queue.put(_sse_event("task_progress", {
                        "task_id": task_id,
                        "detail": detail,
                    }))

                    tool_result = await _execute_tool(block.name, block.input, account_ids, db)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_result,
                    })

            task_messages.append({"role": "assistant", "content": assistant_content})
            task_messages.append({"role": "user", "content": tool_results})

        # Exceeded max rounds -- force a summary
        if not task_completed:
            try:
                task_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": (
                            "You have reached the tool call limit. "
                            "STOP making tool calls. Based on everything you have "
                            "found so far, provide a summary of your findings for "
                            "this task. Include all email IDs, product names, "
                            "dates, and other details you discovered."
                        ),
                    }],
                })
                wrap_response = await client.messages.create(
                    model=execute_model,
                    max_tokens=4096,
                    system=EXECUTE_SYSTEM_PROMPT,
                    messages=task_messages,
                )
                tokens_used += wrap_response.usage.input_tokens + wrap_response.usage.output_tokens
                text_parts = [b.text for b in wrap_response.content if hasattr(b, "text")]
                summary = "\n".join(text_parts) if text_parts else "Task reached max iterations."
            except Exception:
                summary = "Task reached maximum tool call rounds without completing."

            await event_queue.put(_sse_event("task_complete", {
                "task_id": task_id,
                "summary": summary[:500],
            }))
            return task_id, summary, tokens_used


# ---------------------------------------------------------------------------
# ChatService -- main service
# ---------------------------------------------------------------------------

class ChatService:
    def __init__(self):
        self._async_client = None

    def _get_async_client(self):
        if self._async_client is None:
            import anthropic
            api_key = settings.claude_api_key
            if not api_key:
                raise ValueError("Claude API key not configured")
            self._async_client = anthropic.AsyncAnthropic(api_key=api_key)
        return self._async_client

    def _get_models(self, user: User) -> tuple[str, str, str]:
        prefs = user.ai_preferences or {}
        plan_model = prefs.get("chat_plan_model", DEFAULT_AI_PREFERENCES["chat_plan_model"])
        execute_model = prefs.get("chat_execute_model", DEFAULT_AI_PREFERENCES["chat_execute_model"])
        verify_model = prefs.get("chat_verify_model", DEFAULT_AI_PREFERENCES["chat_verify_model"])
        return plan_model, execute_model, verify_model

    def _build_tools(self) -> list[dict]:
        tools = [
            LIST_SENDER_DOMAINS_TOOL,
            SEARCH_EMAILS_TOOL,
            READ_EMAIL_TOOL,
            READ_EMAILS_BATCH_TOOL,
            READ_ATTACHMENT_TOOL,
        ]
        if settings.brave_search_api_key:
            tools.append(WEB_SEARCH_TOOL)
        return tools

    async def run_chat(
        self,
        user_query: str,
        user: User,
        account_ids: list[int],
        db: AsyncSession,
        conversation_history: list[dict] = None,
        account_contexts: list[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """Run the three-phase Plan-Execute-Verify agent. Yields SSE strings.

        account_contexts: list of {"email": ..., "description": ...} for each connected account.
        """
        client = self._get_async_client()
        plan_model, execute_model, verify_model = self._get_models(user)
        tools = self._build_tools()
        total_tokens = 0

        # Build user context supplement for system prompts
        user_context_block = ""
        about_me = getattr(user, "about_me", None)
        if about_me or account_contexts:
            parts = ["\n\nUSER CONTEXT (use this to understand the user's role, priorities, and how to tailor your answers):"]
            if about_me:
                parts.append(f"About the user: {about_me}")
            if account_contexts:
                parts.append("Connected email accounts:")
                for ac in account_contexts:
                    desc = ac.get("description")
                    if desc:
                        parts.append(f"  - {ac['email']}: {desc}")
                    else:
                        parts.append(f"  - {ac['email']}")
            user_context_block = "\n".join(parts)

        plan_system = PLAN_SYSTEM_PROMPT + user_context_block
        verify_system = VERIFY_SYSTEM_PROMPT + user_context_block

        # ─── PHASE 1: PLAN ────────────────────────────────────────────
        yield _sse_event("phase", {"phase": "plan"})

        # Build plan messages with conversation history for context
        plan_messages = []
        if conversation_history:
            for msg in conversation_history:
                plan_messages.append({"role": msg["role"], "content": msg["content"]})
        # Always end with the current user query
        plan_messages.append({"role": "user", "content": user_query})

        try:
            plan_response = await client.messages.create(
                model=plan_model,
                max_tokens=4096,
                system=plan_system,
                messages=plan_messages,
            )
            total_tokens += plan_response.usage.input_tokens + plan_response.usage.output_tokens

            plan_text = plan_response.content[0].text.strip()
            if plan_text.startswith("```"):
                lines = plan_text.split("\n")
                plan_text = "\n".join(lines[1:-1])

            plan_data = json.loads(plan_text)

            # Check if the model is asking for clarification
            if "clarification" in plan_data and not plan_data.get("tasks"):
                question = plan_data["clarification"]
                yield _sse_event("clarification", {"question": question})
                yield _sse_event("done", {"tokens_used": total_tokens, "needs_reply": True})
                return

            tasks = plan_data.get("tasks", [])[:MAX_TASKS]

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Plan phase failed: {e}")
            tasks = [{
                "id": 1,
                "description": f"Search emails related to: {user_query}",
                "search_strategy": "Broad full-text search",
                "depends_on": [],
            }]

        # Ensure every task has depends_on
        for t in tasks:
            if "depends_on" not in t:
                t["depends_on"] = []

        yield _sse_event("plan_ready", {"tasks": tasks})

        # ─── PHASE 2: EXECUTE (parallel waves) ────────────────────────
        yield _sse_event("phase", {"phase": "execute"})
        all_results = {}

        waves = _compute_waves(tasks)
        logger.info(f"Executing {len(tasks)} tasks in {len(waves)} wave(s): {[[t['id'] for t in w] for w in waves]}")

        for wave_idx, wave in enumerate(waves):
            if len(wave) == 1:
                # Single task -- run directly, yielding events inline
                task = wave[0]
                event_queue = asyncio.Queue()

                async def drain_queue():
                    """Collect events from the queue (used after task completes)."""
                    events = []
                    while not event_queue.empty():
                        events.append(event_queue.get_nowait())
                    return events

                # Run the task
                coro = _run_single_task(
                    task, user_query, tasks, all_results,
                    account_ids, execute_model, tools, event_queue,
                )
                result = await coro
                # Yield all queued events
                for evt in await drain_queue():
                    yield evt

                if result:
                    tid, summary, tok = result
                    all_results[tid] = summary
                    total_tokens += tok

            else:
                # Multiple tasks -- run in parallel
                event_queue = asyncio.Queue()

                coros = [
                    _run_single_task(
                        t, user_query, tasks, all_results,
                        account_ids, execute_model, tools, event_queue,
                    )
                    for t in wave
                ]

                # Run all tasks concurrently; drain events periodically
                task_futures = [asyncio.create_task(c) for c in coros]

                # Drain events while tasks are running
                while not all(f.done() for f in task_futures):
                    while not event_queue.empty():
                        yield event_queue.get_nowait()
                    await asyncio.sleep(0.1)

                # Drain remaining events
                while not event_queue.empty():
                    yield event_queue.get_nowait()

                # Collect results
                for f in task_futures:
                    try:
                        result = f.result()
                        if result:
                            tid, summary, tok = result
                            all_results[tid] = summary
                            total_tokens += tok
                    except Exception as e:
                        logger.error(f"Task in wave {wave_idx} failed: {e}")

        # ─── PHASE 3: VERIFY ─────────────────────────────────────────
        yield _sse_event("phase", {"phase": "verify"})

        results_text = ""
        for task in tasks:
            tid = task["id"]
            results_text += f"\n### Task {tid}: {task.get('description', '')}\n"
            results_text += all_results.get(tid, "No results.") + "\n"

        verify_prompt = (
            f"## Original Question\n{user_query}\n\n"
            f"## Research Plan\n{json.dumps(tasks, indent=2)}\n\n"
            f"## Research Results\n{results_text}\n\n"
            f"Based on these research results, produce a comprehensive, well-formatted "
            f"markdown answer to the original question. Include all relevant details found. "
            f"If images were found via web search, include them. If information is incomplete, "
            f"note what was missing."
        )

        try:
            verify_response = await client.messages.create(
                model=verify_model,
                max_tokens=16000,
                system=verify_system,
                messages=[{"role": "user", "content": verify_prompt}],
            )
            total_tokens += verify_response.usage.input_tokens + verify_response.usage.output_tokens

            final_markdown = ""
            for block in verify_response.content:
                if hasattr(block, "text"):
                    final_markdown += block.text

        except Exception as e:
            logger.error(f"Verify phase failed: {e}")
            final_markdown = f"# Results\n\n{results_text}"

        # Validate image URLs in the markdown -- remove broken ones
        final_markdown = await _validate_markdown_images(final_markdown)

        yield _sse_event("content", {"text": final_markdown})
        yield _sse_event("done", {"tokens_used": total_tokens})
