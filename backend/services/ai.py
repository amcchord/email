import asyncio
import logging
import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from backend.models.email import Email
from backend.models.ai import AIAnalysis
from backend.models.user import User
from backend.config import get_settings
from backend.database import async_session
from backend.schemas.auth import DEFAULT_AI_PREFERENCES

logger = logging.getLogger(__name__)
settings = get_settings()

# Max concurrent Claude API calls during batch processing
CONCURRENCY = 5


def _parse_list_unsubscribe(raw_headers: dict) -> Optional[dict]:
    """Parse the List-Unsubscribe header (RFC 2369) into structured info.

    Returns dict with keys: method, email, url, mailto_subject, mailto_body
    or None if no unsubscribe header found.
    """
    header_value = raw_headers.get("list-unsubscribe", "")
    if not header_value:
        return None

    result = {
        "method": None,
        "email": None,
        "url": None,
        "mailto_subject": None,
        "mailto_body": None,
    }

    # Extract all <...> entries from the header
    entries = re.findall(r"<([^>]+)>", header_value)

    for entry in entries:
        entry = entry.strip()
        if entry.lower().startswith("mailto:"):
            # Parse mailto: URI
            mailto_part = entry[7:]  # strip "mailto:"
            if "?" in mailto_part:
                email_addr, query = mailto_part.split("?", 1)
                params = parse_qs(query)
                result["mailto_subject"] = unquote(params.get("subject", ["unsubscribe"])[0])
                result["mailto_body"] = unquote(params.get("body", [""])[0])
            else:
                email_addr = mailto_part
                result["mailto_subject"] = "unsubscribe"
            result["email"] = email_addr.strip()
        elif entry.lower().startswith("http://") or entry.lower().startswith("https://"):
            result["url"] = entry

    if result["email"] and result["url"]:
        result["method"] = "both"
    elif result["email"]:
        result["method"] = "email"
    elif result["url"]:
        result["method"] = "url"
    else:
        return None

    return result


async def get_model_for_user(user_id: int) -> str:
    """Read the agentic_model preference for a user, falling back to the default."""
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.ai_preferences:
            return user.ai_preferences.get(
                "agentic_model",
                DEFAULT_AI_PREFERENCES["agentic_model"],
            )
    return DEFAULT_AI_PREFERENCES["agentic_model"]


class AIService:
    def __init__(self, model: Optional[str] = None):
        self.client = None
        self.model = model or DEFAULT_AI_PREFERENCES["agentic_model"]

    def _get_client(self):
        if self.client is None:
            import anthropic
            api_key = settings.claude_api_key
            if not api_key:
                raise ValueError("Claude API key not configured")
            self.client = anthropic.Anthropic(api_key=api_key)
        return self.client

    async def _call_claude(self, model: str, max_tokens: int, messages: list) -> object:
        """Call Claude API in a thread to avoid blocking the async event loop."""
        client = self._get_client()
        return await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )

    async def analyze_email(self, email_id: int, db: Optional[AsyncSession] = None) -> Optional[AIAnalysis]:
        """Analyze a single email with Claude."""
        close_session = False
        if db is None:
            db = async_session()
            await db.__aenter__()
            close_session = True

        try:
            result = await db.execute(select(Email).where(Email.id == email_id))
            email = result.scalar_one_or_none()
            if not email:
                return None

            # Check if already analyzed
            result = await db.execute(
                select(AIAnalysis).where(AIAnalysis.email_id == email_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing

            # Deterministically parse List-Unsubscribe header
            unsub_info = None
            if email.raw_headers:
                unsub_info = _parse_list_unsubscribe(email.raw_headers)

            # Build analysis prompt
            body = email.body_text or email.snippet or ""
            if len(body) > 5000:
                body = body[:5000] + "..."

            # Include List-Unsubscribe hint so the AI can factor it in
            unsub_hint = ""
            if unsub_info:
                unsub_hint = "\nNote: This email has a List-Unsubscribe header (it is likely a subscription/marketing email)."

            prompt = f"""Analyze this email and provide a structured analysis.

From: {email.from_name or ''} <{email.from_address or ''}>
To: {json.dumps(email.to_addresses or [])}
Subject: {email.subject or '(no subject)'}
Date: {email.date}
{unsub_hint}
Body:
{body}

Respond with ONLY valid JSON in this exact format:
{{
    "category": "<one of: needs_response, can_ignore, fyi, urgent, awaiting_reply>",
    "priority": <0-3 where 0=low 1=normal 2=high 3=urgent>,
    "summary": "<1-2 sentence summary of what this email is about>",
    "action_items": ["<list of specific action items or requests>"],
    "key_topics": ["<main topics discussed>"],
    "sentiment": <float from -1.0 negative to 1.0 positive>,
    "context": {{
        "what_they_want": "<what the sender is asking for or communicating>",
        "deadline": "<any mentioned deadlines or null>",
        "requires_action": <true/false>
    }},
    "suggested_reply": "<brief suggested reply if response needed, or null>",
    "is_subscription": <true if this is a newsletter, marketing, automated notification, mailing list, or bulk email; false if personal/direct>,
    "needs_reply": <true if the recipient should write back to this email; false if no reply needed>
}}"""

            response = await self._call_claude(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()

            # Parse JSON response
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])

            analysis_data = json.loads(response_text)
            tokens_used = response.usage.input_tokens + response.usage.output_tokens

            analysis = AIAnalysis(
                email_id=email_id,
                category=analysis_data.get("category", "fyi"),
                priority=analysis_data.get("priority", 1),
                summary=analysis_data.get("summary"),
                action_items=analysis_data.get("action_items", []),
                context=analysis_data.get("context", {}),
                sentiment=analysis_data.get("sentiment"),
                key_topics=analysis_data.get("key_topics", []),
                suggested_reply=analysis_data.get("suggested_reply"),
                is_subscription=analysis_data.get("is_subscription", False),
                needs_reply=analysis_data.get("needs_reply", False),
                unsubscribe_info=unsub_info,
                model_used=self.model,
                tokens_used=tokens_used,
            )
            db.add(analysis)
            await db.commit()
            await db.refresh(analysis)

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response for email {email_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"AI analysis error for email {email_id}: {e}")
            return None
        finally:
            if close_session:
                await db.__aexit__(None, None, None)

    async def analyze_thread(self, thread_id: str) -> Optional[dict]:
        """Analyze an entire thread for context."""
        async with async_session() as db:
            result = await db.execute(
                select(Email).where(Email.gmail_thread_id == thread_id).order_by(Email.date)
            )
            emails = result.scalars().all()
            if not emails:
                return None

            thread_text = ""
            for e in emails:
                body = e.body_text or e.snippet or ""
                if len(body) > 2000:
                    body = body[:2000] + "..."
                thread_text += f"\n---\nFrom: {e.from_name} <{e.from_address}>\nDate: {e.date}\nSubject: {e.subject}\n\n{body}\n"

            if len(thread_text) > 15000:
                thread_text = thread_text[:15000] + "\n... (truncated)"

            prompt = f"""Analyze this email thread and provide a comprehensive summary.

{thread_text}

Respond with ONLY valid JSON:
{{
    "thread_summary": "<comprehensive summary of the entire thread>",
    "key_decisions": ["<any decisions made>"],
    "open_questions": ["<unresolved questions>"],
    "action_items": ["<action items with who is responsible>"],
    "latest_status": "<current status of the conversation>",
    "participants_context": {{"<email>": "<role/context for each participant>"}}
}}"""

            try:
                response = await self._call_claude(
                    model=self.model,
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt}],
                )

                response_text = response.content[0].text.strip()
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    response_text = "\n".join(lines[1:-1])

                return json.loads(response_text)

            except Exception as e:
                logger.error(f"Thread analysis error: {e}")
                return None

    async def batch_categorize(self, email_ids: list[int]):
        """Batch categorize emails with parallel processing."""
        sem = asyncio.Semaphore(CONCURRENCY)

        async def process_one(eid):
            async with sem:
                try:
                    await self.analyze_email(eid)
                except Exception as e:
                    logger.error(f"Batch categorize error for {eid}: {e}")

        await asyncio.gather(*[process_one(eid) for eid in email_ids], return_exceptions=True)

    async def draft_action_reply(self, todo_id: int) -> dict:
        """Draft a reply for a todo item's action item, using the source email as context."""
        from backend.models.todo import TodoItem

        async with async_session() as db:
            result = await db.execute(select(TodoItem).where(TodoItem.id == todo_id))
            todo = result.scalar_one_or_none()
            if not todo:
                raise ValueError(f"Todo {todo_id} not found")
            if not todo.email_id:
                raise ValueError("Todo has no source email")

            # Get the source email
            email_result = await db.execute(select(Email).where(Email.id == todo.email_id))
            email = email_result.scalar_one_or_none()
            if not email:
                raise ValueError("Source email not found")

            body = email.body_text or email.snippet or ""
            if len(body) > 3000:
                body = body[:3000] + "..."

            prompt = f"""You need to draft a reply to an email to address a specific action item.

Original email:
From: {email.from_name or ''} <{email.from_address or ''}>
Subject: {email.subject or '(no subject)'}
Date: {email.date}

Body:
{body}

Action item to address: {todo.title}

Write a concise, professional reply that addresses this specific action item. Write ONLY the reply text, no subject line or headers. Keep it brief and natural."""

            try:
                response = await self._call_claude(
                    model=self.model,
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )

                draft_body = response.content[0].text.strip()
                reply_to = email.reply_to or email.from_address

                # Save to the todo
                todo.ai_draft_status = "ready"
                todo.ai_draft_body = draft_body
                todo.ai_draft_to = reply_to
                await db.commit()

                return {
                    "id": todo.id,
                    "ai_draft_status": "ready",
                    "ai_draft_body": draft_body,
                    "ai_draft_to": reply_to,
                }

            except Exception as e:
                logger.error(f"Draft action error for todo {todo_id}: {e}")
                todo.ai_draft_status = None
                await db.commit()
                raise

    async def auto_categorize_newest(self, account_id: int, limit: int = 1000) -> int:
        """Categorize the newest `limit` emails for an account that haven't been analyzed yet.

        Uses parallel processing with a concurrency semaphore for speed.
        Returns the count of emails analyzed.
        """
        async with async_session() as db:
            # Get the newest `limit` emails that don't have an AIAnalysis row
            subquery = select(AIAnalysis.email_id)
            result = await db.execute(
                select(Email.id).where(
                    Email.account_id == account_id,
                    ~Email.id.in_(subquery),
                    Email.is_trash == False,
                    Email.is_spam == False,
                ).order_by(desc(Email.date)).limit(limit)
            )
            email_ids = [r[0] for r in result.all()]

        if not email_ids:
            logger.info(f"No unanalyzed emails found for account {account_id}")
            return 0

        logger.info(f"Auto-categorizing {len(email_ids)} emails for account {account_id} (concurrency={CONCURRENCY})")

        analyzed = 0
        sem = asyncio.Semaphore(CONCURRENCY)

        async def process_one(eid):
            nonlocal analyzed
            async with sem:
                try:
                    result = await self.analyze_email(eid)
                    if result:
                        analyzed += 1
                except Exception as e:
                    logger.error(f"Auto-categorize error for email {eid}: {e}")

        await asyncio.gather(*[process_one(eid) for eid in email_ids], return_exceptions=True)

        logger.info(f"Auto-categorized {analyzed}/{len(email_ids)} emails for account {account_id}")
        return analyzed
