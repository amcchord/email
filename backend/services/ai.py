import logging
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.email import Email
from backend.models.ai import AIAnalysis
from backend.config import get_settings
from backend.database import async_session

logger = logging.getLogger(__name__)
settings = get_settings()


class AIService:
    def __init__(self):
        self.client = None

    def _get_client(self):
        if self.client is None:
            import anthropic
            api_key = settings.claude_api_key
            if not api_key:
                raise ValueError("Claude API key not configured")
            self.client = anthropic.Anthropic(api_key=api_key)
        return self.client

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

            # Build analysis prompt
            body = email.body_text or email.snippet or ""
            if len(body) > 5000:
                body = body[:5000] + "..."

            prompt = f"""Analyze this email and provide a structured analysis.

From: {email.from_name or ''} <{email.from_address or ''}>
To: {json.dumps(email.to_addresses or [])}
Subject: {email.subject or '(no subject)'}
Date: {email.date}

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
    "suggested_reply": "<brief suggested reply if response needed, or null>"
}}"""

            client = self._get_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
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
                model_used="claude-sonnet-4-20250514",
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
                client = self._get_client()
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
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
        """Batch categorize emails."""
        for email_id in email_ids:
            try:
                await self.analyze_email(email_id)
            except Exception as e:
                logger.error(f"Batch categorize error for {email_id}: {e}")
                continue
