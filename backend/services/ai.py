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
from backend.services.ai_models import (
    ALLOWED_MODELS,
    CHEAP_MODEL,
    DEFAULT_AI_PREFERENCES,
    base_model_id,
    is_fast_variant,
    is_valid_model,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Max concurrent Claude API calls during batch processing
CONCURRENCY = 5

# Allowed values for AIAnalysis.reply_options[*].intent
VALID_REPLY_INTENTS: frozenset[str] = frozenset(
    {"accept", "decline", "defer", "custom", "not_relevant"}
)


# ---------------------------------------------------------------------------
# Cacheable system prompts (pure static text — no per-email substitutions)
# ---------------------------------------------------------------------------

ANALYZE_EMAIL_SYSTEM = """You are an expert email triage assistant. The user will give you a single email and per-email context. Respond with ONLY valid JSON in this exact format (no markdown fences, no commentary):

{
    "category": "<one of: can_ignore, fyi, urgent, awaiting_reply>",
    "email_type": "<one of: work, personal>",
    "conversation_type": "<one of: scheduling, discussion, notification, transactional, other>",
    "priority": <0-3 where 0=low 1=normal 2=high 3=urgent>,
    "summary": "<1-2 sentence summary of what this email is about>",
    "action_items": ["<list of specific action items or requests>"],
    "key_topics": ["<main topics discussed>"],
    "sentiment": <float from -1.0 negative to 1.0 positive>,
    "context": {
        "what_they_want": "<what the sender is asking for or communicating>",
        "deadline": "<any mentioned deadlines or null>",
        "requires_action": <true/false>
    },
    "suggested_reply": "<brief best-fit suggested reply if response needed, or null>",
    "reply_options": <array of reply option objects or null. Each object has: "label" (short button text like "Accept", "Decline", "Not now", "Reply"), "intent" (one of: accept, decline, defer, custom, not_relevant), "body" (the full reply text). Provide 2-4 options when a reply is needed, or null if no reply is needed.>,
    "is_subscription": <true if this is a newsletter, marketing, automated notification, mailing list, bulk email, cold sales outreach, unsolicited pitch, or vendor solicitation; false if personal/direct from someone the user has a relationship with>,
    "needs_reply": <true if the recipient should write back to this email; false if no reply needed>
}

conversation_type guide:
- "scheduling": meeting requests, availability discussions, calendar invites, rescheduling, booking confirmations
- "discussion": back-and-forth conversation, brainstorming, debate, Q&A threads
- "notification": automated alerts, system notifications, status updates, delivery updates
- "transactional": receipts, order confirmations, password resets, account verification
- "other": anything that does not fit the above categories

reply_options guide (for SCHEDULING emails):
- ALWAYS include an "accept" option with a friendly acceptance reply body
- ALWAYS include a "decline" option with a polite decline reply body
- If calendar events show a conflict at the proposed time, mention the conflict in the decline body (but do NOT reveal the conflicting event title)
- Optionally include a "defer" option suggesting alternative times or asking to check back later
- If the user has a scheduling assistant, suggest coordinating through them

reply_options guide (for NON-SCHEDULING emails):
- If the email needs a reply, include a "custom" option with a helpful default reply body
- Include a "not_relevant" option with label "Not for me" if the email could be misdirected or not relevant
- Include a "defer" option with label "Not now" if the reply could reasonably be deferred
- If the email does NOT need a reply, reply_options should be null

cold outreach / spam detection guide:
Cold sales emails are crafted to avoid spam filters -- they use subtle, polite language instead of obvious keywords. Watch for these signals:
- SOFT OPT-OUT LANGUAGE (strongest signal): Any variant of "you can tell me to go away" from a first-time sender is cold outreach. Examples: "just let me know if this isn't relevant", "feel free to ignore this", "no worries if the timing isn't right", "happy to stop reaching out", "if you're not the right person just say so", "just say no thank you", "not a fit? no problem", "if you want me to stop messaging". A legitimate contact would NEVER preemptively offer the recipient a way to make them go away.
- MEETING/CALL REQUESTS FROM UNKNOWN SENDERS: If there is no prior conversation and someone asks for a call, meeting, demo, or "15 minutes of your time", treat it as cold outreach.
- SUBTLE SALES PATTERNS: "I came across your company", "I noticed you're using X", "companies like yours", "we help teams with", "quick question for you", "checking in" (with no prior thread), "following up on my last email" (when there is no prior conversation), "would love to connect", "curious if you've thought about", "I'd love to show you".
When cold outreach is detected: set is_subscription=true, needs_reply=false, category="can_ignore", priority=0. Do NOT suggest the user reply to cold outreach."""


CLASSIFY_SENT_SYSTEM = """You decide whether a sent email expects a reply from the recipient. Respond with ONLY valid JSON: {"expects_reply": <true|false>}. expects_reply is true if the sender is asking a question, making a request, or otherwise expects the recipient to respond; false if this is a closing message, confirmation, acknowledgment, or statement that does not require a response."""


THREAD_ANALYSIS_SYSTEM = """You analyze entire email threads. Respond with ONLY valid JSON (no markdown fences) in this exact format:

{
    "thread_summary": "<comprehensive summary of the entire thread>",
    "conversation_type": "<one of: scheduling, discussion, notification, transactional, other>",
    "resolved_outcome": "<if scheduling: the final confirmed time/place/details, e.g. 'Meeting confirmed for Wednesday 2pm at Coffee Shop'. If discussion: the conclusion reached. null if unresolved or not applicable>",
    "is_resolved": <true if the conversation has reached a conclusion or agreement, false if still open/pending>,
    "key_decisions": ["<any decisions made>"],
    "key_topics": ["<main topics discussed>"],
    "open_questions": ["<unresolved questions>"],
    "action_items": ["<action items with who is responsible>"],
    "latest_status": "<current status of the conversation>",
    "participants_context": {"<email>": "<role/context for each participant>"}
}

conversation_type guide:
- "scheduling": meeting requests, availability discussions, calendar invites, rescheduling, booking confirmations
- "discussion": back-and-forth conversation, brainstorming, debate, Q&A threads
- "notification": automated alerts, system notifications, status updates
- "transactional": receipts, order confirmations, password resets
- "other": anything that does not fit the above categories"""


CUSTOM_REPLY_SYSTEM = """You are an intelligent email assistant. The user is looking at an email and has given you an instruction. Decide whether to draft a reply to the current thread OR compose an entirely new email, then call the `compose_email` tool with your decision.

Guidelines:
- If the instruction mentions introducing, connecting, or forwarding someone to a new person, that is a NEW email (is_new_email: true). Put both parties in the TO field so they can both see and reply.
- For introductions, write a warm, professional intro that explains who each person is and why they should connect, using context from the email thread.
- If the instruction is about replying, declining, accepting, deferring, or otherwise responding to the sender, that is a reply (is_new_email: false).
- Extract any email addresses mentioned in the user's instruction for the to/cc fields.
- If the user mentions a person by name but no email address, use the email address from the current email context if it matches, otherwise include the name in the body and leave it out of to/cc.
- Write naturally and concisely. Match the user's tone from the instruction."""


# ---------------------------------------------------------------------------
# Structured-output tool schemas (forced via tool_choice)
# ---------------------------------------------------------------------------

ANALYZE_EMAIL_TOOL = {
    "name": "record_email_analysis",
    "description": "Record the structured analysis of an email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["can_ignore", "fyi", "urgent", "awaiting_reply"]},
            "email_type": {"type": "string", "enum": ["work", "personal"]},
            "conversation_type": {
                "type": "string",
                "enum": ["scheduling", "discussion", "notification", "transactional", "other"],
            },
            "priority": {"type": "integer", "minimum": 0, "maximum": 3},
            "summary": {"type": "string"},
            "action_items": {"type": "array", "items": {"type": "string"}},
            "key_topics": {"type": "array", "items": {"type": "string"}},
            "sentiment": {"type": "number", "minimum": -1, "maximum": 1},
            "context": {
                "type": "object",
                "properties": {
                    "what_they_want": {"type": "string"},
                    "deadline": {"type": ["string", "null"]},
                    "requires_action": {"type": "boolean"},
                },
            },
            "suggested_reply": {"type": ["string", "null"]},
            "reply_options": {
                "type": ["array", "null"],
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "intent": {"type": "string", "enum": list(VALID_REPLY_INTENTS)},
                        "body": {"type": "string"},
                    },
                    "required": ["label", "intent", "body"],
                },
            },
            "is_subscription": {"type": "boolean"},
            "needs_reply": {"type": "boolean"},
        },
        "required": [
            "category", "email_type", "conversation_type", "priority",
            "summary", "is_subscription", "needs_reply",
        ],
    },
}

CLASSIFY_SENT_TOOL = {
    "name": "record_expects_reply",
    "description": "Record whether the sent email expects a reply.",
    "input_schema": {
        "type": "object",
        "properties": {"expects_reply": {"type": "boolean"}},
        "required": ["expects_reply"],
    },
}

THREAD_ANALYSIS_TOOL = {
    "name": "record_thread_analysis",
    "description": "Record the structured analysis of an email thread.",
    "input_schema": {
        "type": "object",
        "properties": {
            "thread_summary": {"type": "string"},
            "conversation_type": {
                "type": "string",
                "enum": ["scheduling", "discussion", "notification", "transactional", "other"],
            },
            "resolved_outcome": {"type": ["string", "null"]},
            "is_resolved": {"type": "boolean"},
            "key_decisions": {"type": "array", "items": {"type": "string"}},
            "key_topics": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "action_items": {"type": "array", "items": {"type": "string"}},
            "latest_status": {"type": "string"},
            "participants_context": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["thread_summary", "conversation_type", "is_resolved"],
    },
}

THREAD_MERGE_TOOL = {
    "name": "record_thread_merge_decision",
    "description": "Record whether the new email belongs to the candidate thread.",
    "input_schema": {
        "type": "object",
        "properties": {
            "should_merge": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["should_merge", "confidence", "reason"],
    },
}

CUSTOM_REPLY_TOOL = {
    "name": "compose_email",
    "description": "Either draft a reply to the current thread or compose a new email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_new_email": {"type": "boolean"},
            "to": {"type": ["array", "null"], "items": {"type": "string"}},
            "cc": {"type": ["array", "null"], "items": {"type": "string"}},
            "subject": {"type": ["string", "null"]},
            "body": {"type": "string"},
        },
        "required": ["is_new_email", "body"],
    },
}


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
            model = user.ai_preferences.get("agentic_model")
            if is_valid_model(model):
                return model
    return DEFAULT_AI_PREFERENCES["agentic_model"]


async def get_unsubscribe_model_for_user(user_id: int) -> str:
    """Read the unsubscribe_model preference for a user, falling back to the default."""
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.ai_preferences:
            model = user.ai_preferences.get("unsubscribe_model")
            if is_valid_model(model):
                return model
    return DEFAULT_AI_PREFERENCES["unsubscribe_model"]


async def get_custom_prompt_model_for_user(user_id: int) -> str:
    """Read the custom_prompt_model preference for a user.

    Falls back to agentic_model, then to the default.
    """
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.ai_preferences:
            custom = user.ai_preferences.get("custom_prompt_model")
            if is_valid_model(custom):
                return custom
            agentic = user.ai_preferences.get("agentic_model")
            if is_valid_model(agentic):
                return agentic
    return DEFAULT_AI_PREFERENCES["custom_prompt_model"]


def _strip_quoted_text(body: str) -> str:
    """Strip quoted reply content and signatures from an email body.

    Removes:
    - Everything after an 'On ... wrote:' reply header
    - Lines starting with '>'
    - Signature blocks starting with '-- '
    """
    # Remove everything from "On ... wrote:" onwards
    body = re.sub(r'\r?\nOn [^\n]+wrote:\s*[\s\S]*$', '', body)
    # Remove signature blocks
    body = re.sub(r'\r?\n-- ?\r?\n[\s\S]*$', '', body)
    # Remove individual quoted lines (lines starting with >)
    body = re.sub(r'(^|\n)>.*', '', body)
    return body.strip()


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

    async def _call_claude_tool(
        self,
        model: str,
        max_tokens: int,
        messages: list,
        tool: dict,
        system: Optional[str | list] = None,
    ) -> tuple[Optional[dict], int]:
        """Force the model to call `tool` and return (parsed_input, tokens_used).

        This eliminates the "respond with ONLY JSON" / `json.loads` / strip-
        markdown-fences dance. Returns (None, tokens_used) if the model
        somehow doesn't call the tool (defensive — should not happen with
        tool_choice).
        """
        client = self._get_client()
        use_fast = is_fast_variant(model)
        api_model = base_model_id(model)

        kwargs = {
            "model": api_model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"]},
        }
        if system is not None:
            if isinstance(system, str):
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                kwargs["system"] = system

        if use_fast:
            kwargs["betas"] = ["fast-mode-2026-02-01"]
            response = await asyncio.to_thread(client.beta.messages.create, **kwargs)
        else:
            response = await asyncio.to_thread(client.messages.create, **kwargs)

        tokens = 0
        usage = getattr(response, "usage", None)
        if usage:
            tokens = (usage.input_tokens or 0) + (usage.output_tokens or 0)

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
                return block.input, tokens

        return None, tokens

    async def _call_claude(
        self,
        model: str,
        max_tokens: int,
        messages: list,
        system: Optional[str | list] = None,
        cache_system: bool = True,
    ) -> object:
        """Call Claude API in a thread to avoid blocking the async event loop.

        If `system` is a string and `cache_system` is True, it is wrapped in
        a list with `cache_control: ephemeral` so subsequent calls with the
        same system prompt hit Anthropic's prompt cache (~90% discount on
        the cached input tokens).
        """
        client = self._get_client()
        use_fast = is_fast_variant(model)
        api_model = base_model_id(model)

        kwargs = {
            "model": api_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system is not None:
            if isinstance(system, str) and cache_system:
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                kwargs["system"] = system

        if use_fast:
            kwargs["betas"] = ["fast-mode-2026-02-01"]
            return await asyncio.to_thread(client.beta.messages.create, **kwargs)
        return await asyncio.to_thread(client.messages.create, **kwargs)

    async def _get_upcoming_events_context(self, account_id: int, days: int = 14) -> str:
        """Query upcoming calendar events for context injection."""
        from datetime import timedelta as _td
        from sqlalchemy import or_, and_
        from backend.models.calendar import CalendarEvent

        now = datetime.now(timezone.utc)
        end_dt = now + _td(days=days)
        end_str = end_dt.strftime("%Y-%m-%d")
        now_str = now.strftime("%Y-%m-%d")

        async with async_session() as db:
            # Fetch both timed and all-day events
            timed_condition = and_(
                CalendarEvent.is_all_day == False,
                CalendarEvent.start_time >= now,
                CalendarEvent.start_time <= end_dt,
            )
            allday_condition = and_(
                CalendarEvent.is_all_day == True,
                CalendarEvent.start_date >= now_str,
                CalendarEvent.start_date <= end_str,
            )
            result = await db.execute(
                select(CalendarEvent)
                .where(
                    CalendarEvent.account_id == account_id,
                    CalendarEvent.status != "cancelled",
                    or_(timed_condition, allday_condition),
                )
                .order_by(CalendarEvent.start_time.asc().nulls_last())
                .limit(30)
            )
            events = result.scalars().all()

        if not events:
            return ""

        lines = []
        for e in events:
            title = e.summary or "(no title)"
            if e.is_all_day:
                lines.append(f"  - {e.start_date} (all day): {title}")
            else:
                start_str = e.start_time.strftime("%a %b %d, %I:%M %p") if e.start_time else "?"
                end_str_fmt = e.end_time.strftime("%I:%M %p") if e.end_time else "?"
                entry = f"  - {start_str} - {end_str_fmt}: {title}"
                if e.location:
                    entry += f" ({e.location})"
                attendee_count = len(e.attendees) if e.attendees else 0
                if attendee_count > 0:
                    entry += f" [{attendee_count} attendees]"
                lines.append(entry)

        return (
            f"\nUpcoming calendar events (next {days} days):\n"
            + "\n".join(lines)
            + "\nUse this calendar context to identify scheduling conflicts. "
            "If a proposed meeting time overlaps with an existing event, note the conflict.\n\n"
        )

    async def generate_short_label(self, description: str) -> str:
        """Generate a 1-2 word short label from an account description."""
        prompt = (
            f"Given this email account description, produce a concise 1-2 word label "
            f"that identifies the account's purpose. Examples: 'Work', 'Personal', "
            f"'Side Project', 'Freelance', 'School', 'Gaming', 'Shopping', 'Finance', "
            f"'Startup', 'Consulting'.\n\n"
            f"Description: {description}\n\n"
            f"Respond with ONLY the 1-2 word label, nothing else."
        )
        response = await self._call_claude(
            model=CHEAP_MODEL,
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip().strip('"').strip("'")

    async def _build_analyze_prompt(
        self,
        email: Email,
        db: AsyncSession,
        user_context: Optional[str],
        account_description: Optional[str],
        account_email: Optional[str],
        unsub_info: Optional[dict],
    ) -> str:
        """Build the per-email analysis prompt (without the static system text).

        Extracted so both `analyze_email` (realtime) and `batch_categorize_via_messages_batch`
        (Anthropic Message Batches API) can share the same prompt construction.
        """
        # Build analysis prompt
        body = email.body_text or email.snippet or ""
        if len(body) > 5000:
            body = body[:5000] + "..."

        # Include List-Unsubscribe hint so the AI can factor it in
        unsub_hint = ""
        if unsub_info:
            unsub_hint = "\nNote: This email has a List-Unsubscribe header (it is likely a subscription/marketing email)."

        # Build user context preamble
        context_preamble = ""
        context_parts = []
        if account_email:
            context_parts.append(
                f"You are analyzing emails for the inbox of {account_email}. "
                f"This person is the mailbox owner. Any suggested_reply must be written "
                f"FROM {account_email}'s perspective (as if they are writing it), never as "
                f"if someone else is replying to them."
            )
        if user_context:
            context_parts.append(f"About the user: {user_context}")
        if account_description:
            context_parts.append(f"This email is from their account used for: {account_description}")
        if context_parts:
            context_preamble = "\n".join(context_parts) + "\n\nUse this context to prioritize and categorize the email appropriately.\n"

        # Compute email age hint so the AI treats old emails appropriately
        age_hint = ""
        if email.date:
            email_age = datetime.now(timezone.utc) - email.date
            age_days = email_age.days
            if age_days > 30:
                age_hint = (
                    f"\nNote: This email is {age_days} days old. "
                    f"Emails older than 30 days should NOT be considered urgent or high priority — "
                    f"they are effectively expired. Set priority to 0 (low) and do not use the 'urgent' category."
                )
            elif age_days > 7:
                age_hint = f"\nNote: This email is {age_days} days old. Consider this age when assessing urgency."

        # Build thread context so the AI can see if this is part of a
        # conversation and whether the user already replied.
        thread_context = ""
        if email.gmail_thread_id:
            thread_result = await db.execute(
                select(Email)
                .where(
                    Email.gmail_thread_id == email.gmail_thread_id,
                    Email.account_id == email.account_id,
                    Email.id != email.id,
                )
                .order_by(desc(Email.date))
                .limit(5)
            )
            thread_emails = thread_result.scalars().all()
            if thread_emails:
                lines = []
                for te in reversed(thread_emails):
                    direction = "[Sent by you]" if te.is_sent else "[Received]"
                    date_str = te.date.strftime("%Y-%m-%d %H:%M") if te.date else "unknown date"
                    snippet = (te.snippet or "")[:120]
                    lines.append(f"  {direction} {date_str} — {te.from_name or te.from_address}: {snippet}")
                thread_context = (
                    "\n\nThread context (other messages in this conversation, oldest first):\n"
                    + "\n".join(lines)
                    + "\n\nUse this thread context to determine if the user has already replied "
                    "or if the conversation has moved on. If the user already replied after "
                    "this email, set needs_reply to false."
                )
            else:
                thread_context = (
                    "\n\nNote: This is the FIRST email from this sender — there is no prior "
                    "conversation history. Be extra skeptical of meeting requests or pitches "
                    "from first-time senders with no established relationship."
                )

        # Inject calendar context for scheduling-related emails
        calendar_context = ""
        scheduling_keywords = ["meeting", "calendar", "schedule", "invite", "rsvp",
                               "appointment", "call", "sync", "standup", "1:1",
                               "one-on-one", "catch up", "reschedule", "availability"]
        subject_lower = (email.subject or "").lower()
        body_lower = body[:500].lower()
        is_scheduling = any(kw in subject_lower or kw in body_lower for kw in scheduling_keywords)
        if is_scheduling:
            try:
                calendar_context = await self._get_upcoming_events_context(email.account_id)
            except Exception as cal_err:
                logger.debug(f"Could not load calendar context: {cal_err}")

        # Build scheduling assistant hint if the user's context mentions one
        scheduling_assistant_hint = ""
        combined_context = ((user_context or "") + " " + (account_description or "")).lower()
        assistant_keywords = ["assistant", "ea", "executive assistant", "scheduler",
                              "scheduling assistant", "admin assistant", "office manager"]
        has_scheduling_assistant = any(kw in combined_context for kw in assistant_keywords)
        if has_scheduling_assistant:
            scheduling_assistant_hint = (
                "\nNote: The user's context mentions they have a scheduling assistant or similar. "
                "When generating scheduling-related replies, consider suggesting that the sender "
                "coordinate with the assistant or that the user will check with their assistant.\n"
            )

        scheduling_marker = (
            "This IS a scheduling email — follow the scheduling reply_options guide."
            if is_scheduling
            else "This is NOT a scheduling email — follow the non-scheduling reply_options guide."
        )

        return f"""{context_preamble}{calendar_context}{scheduling_assistant_hint}{scheduling_marker}

Analyze this email and provide a structured analysis.

From: {email.from_name or ''} <{email.from_address or ''}>
To: {json.dumps(email.to_addresses or [])}
Subject: {email.subject or '(no subject)'}
Date: {email.date}
{unsub_hint}{age_hint}{thread_context}
Body:
{body}"""

    def _build_analysis_row(
        self,
        email_id: int,
        analysis_data: dict,
        unsub_info: Optional[dict],
        tokens_used: int,
    ) -> AIAnalysis:
        """Convert a `record_email_analysis` tool input into an AIAnalysis row.

        Validates `reply_options` and applies sensible defaults.
        """
        raw_reply_options = analysis_data.get("reply_options")
        reply_options = None
        if raw_reply_options and isinstance(raw_reply_options, list):
            validated = []
            for opt in raw_reply_options:
                if isinstance(opt, dict) and opt.get("label") and opt.get("intent") and opt.get("body"):
                    intent = opt["intent"]
                    if intent in VALID_REPLY_INTENTS:
                        validated.append({
                            "label": str(opt["label"]),
                            "intent": intent,
                            "body": str(opt["body"]),
                        })
            if validated:
                reply_options = validated

        return AIAnalysis(
            email_id=email_id,
            category=analysis_data.get("category", "fyi"),
            email_type=analysis_data.get("email_type", "personal"),
            conversation_type=analysis_data.get("conversation_type", "other"),
            priority=analysis_data.get("priority", 1),
            summary=analysis_data.get("summary"),
            action_items=analysis_data.get("action_items", []),
            context=analysis_data.get("context", {}),
            sentiment=analysis_data.get("sentiment"),
            key_topics=analysis_data.get("key_topics", []),
            suggested_reply=analysis_data.get("suggested_reply"),
            reply_options=reply_options,
            is_subscription=analysis_data.get("is_subscription", False),
            needs_reply=analysis_data.get("needs_reply", False),
            unsubscribe_info=unsub_info,
            model_used=self.model,
            tokens_used=tokens_used,
        )

    async def analyze_email(
        self,
        email_id: int,
        db: Optional[AsyncSession] = None,
        user_context: Optional[str] = None,
        account_description: Optional[str] = None,
        account_email: Optional[str] = None,
    ) -> Optional[AIAnalysis]:
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

            result = await db.execute(
                select(AIAnalysis).where(AIAnalysis.email_id == email_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing

            unsub_info = None
            if email.raw_headers:
                unsub_info = _parse_list_unsubscribe(email.raw_headers)

            prompt = await self._build_analyze_prompt(
                email, db, user_context, account_description, account_email, unsub_info,
            )

            analysis_data, tokens_used = await self._call_claude_tool(
                model=self.model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
                tool=ANALYZE_EMAIL_TOOL,
                system=ANALYZE_EMAIL_SYSTEM,
            )
            if analysis_data is None:
                logger.error(f"AI analysis returned no tool_use for email {email_id}")
                return None

            analysis = self._build_analysis_row(email_id, analysis_data, unsub_info, tokens_used)
            db.add(analysis)
            await db.commit()
            await db.refresh(analysis)

            return analysis

        except Exception as e:
            logger.error(f"AI analysis error for email {email_id}: {e}")
            return None
        finally:
            if close_session:
                await db.__aexit__(None, None, None)

    async def classify_sent_email(
        self,
        email_id: int,
        db: Optional[AsyncSession] = None,
    ) -> Optional[AIAnalysis]:
        """Lightweight classification for sent emails: does this email expect a reply?

        Uses Haiku for minimal cost.  Creates or updates an AIAnalysis row
        with only the expects_reply field populated.
        """
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

            # Check if already classified
            result = await db.execute(
                select(AIAnalysis).where(AIAnalysis.email_id == email_id)
            )
            existing = result.scalar_one_or_none()
            if existing and existing.expects_reply is not None:
                return existing

            # Build the email body, stripping quoted reply content
            body = email.body_text or email.snippet or ""
            body = _strip_quoted_text(body)
            if len(body) > 2000:
                body = body[:2000] + "..."

            # Build thread context so the AI understands the conversation
            thread_context = ""
            if email.gmail_thread_id:
                thread_result = await db.execute(
                    select(Email)
                    .where(
                        Email.gmail_thread_id == email.gmail_thread_id,
                        Email.account_id == email.account_id,
                        Email.id != email.id,
                    )
                    .order_by(desc(Email.date))
                    .limit(5)
                )
                thread_emails = thread_result.scalars().all()
                if thread_emails:
                    lines = []
                    for te in reversed(thread_emails):
                        direction = "[Sent by user]" if te.is_sent else "[Received]"
                        date_str = te.date.strftime("%Y-%m-%d %H:%M") if te.date else "unknown"
                        snippet = (te.snippet or "")[:150]
                        lines.append(f"  {direction} {date_str} — {te.from_name or te.from_address}: {snippet}")
                    thread_context = (
                        "\nThread context (other messages in this conversation, oldest first):\n"
                        + "\n".join(lines) + "\n"
                    )

            prompt = f"""From: {email.from_name or ''} <{email.from_address or ''}>
To: {json.dumps(email.to_addresses or [])}
Subject: {email.subject or '(no subject)'}
Date: {email.date}
{thread_context}
Body (quoted text removed):
{body}"""

            data, tokens_used = await self._call_claude_tool(
                model=CHEAP_MODEL,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
                tool=CLASSIFY_SENT_TOOL,
                system=CLASSIFY_SENT_SYSTEM,
            )
            if data is None:
                logger.error(f"Sent-email classification returned no tool_use for {email_id}")
                return None
            expects_reply = bool(data.get("expects_reply", True))

            if existing:
                existing.expects_reply = expects_reply
                existing.model_used = existing.model_used or CHEAP_MODEL
                await db.commit()
                await db.refresh(existing)
                return existing
            else:
                analysis = AIAnalysis(
                    email_id=email_id,
                    expects_reply=expects_reply,
                    analyzed_at=datetime.now(timezone.utc),
                    model_used=CHEAP_MODEL,
                    tokens_used=tokens_used,
                )
                db.add(analysis)
                await db.commit()
                await db.refresh(analysis)
                return analysis

        except Exception as e:
            logger.error(f"Sent-email classification error for {email_id}: {e}")
            return None
        finally:
            if close_session:
                await db.__aexit__(None, None, None)

    async def analyze_thread(
        self,
        thread_id: str,
        user_context: Optional[str] = None,
        account_description: Optional[str] = None,
    ) -> Optional[dict]:
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
                direction = "[SENT]" if e.is_sent else "[RECEIVED]"
                body = e.body_text or e.snippet or ""
                if len(body) > 2000:
                    body = body[:2000] + "..."
                thread_text += f"\n---\n{direction} From: {e.from_name} <{e.from_address}>\nDate: {e.date}\nSubject: {e.subject}\n\n{body}\n"

            if len(thread_text) > 15000:
                thread_text = thread_text[:15000] + "\n... (truncated)"

            # Build user context preamble
            context_preamble = ""
            if user_context or account_description:
                context_parts = []
                if user_context:
                    context_parts.append(f"About the user: {user_context}")
                if account_description:
                    context_parts.append(f"This thread is from their account used for: {account_description}")
                context_preamble = "\n".join(context_parts) + "\n\nUse this context to provide a more relevant summary.\n\n"

            prompt = f"""{context_preamble}Analyze this email thread and provide a comprehensive summary.

{thread_text}"""

            try:
                data, _ = await self._call_claude_tool(
                    model=self.model,
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt}],
                    tool=THREAD_ANALYSIS_TOOL,
                    system=THREAD_ANALYSIS_SYSTEM,
                )
                return data

            except Exception as e:
                logger.error(f"Thread analysis error: {e}")
                return None

    async def check_thread_merge(
        self,
        email_subject: str,
        email_from: str,
        email_snippet: str,
        candidate_subject: str,
        candidate_participants: list[str],
        candidate_snippet: str,
    ) -> dict:
        """Ask the LLM whether a lone email should be merged into a candidate thread.

        Returns {"should_merge": bool, "confidence": float, "reason": str}.
        """
        prompt = (
            "Given a new email that Gmail placed in its own thread, determine if it "
            "actually belongs to an existing thread, then call the "
            "`record_thread_merge_decision` tool with your decision.\n\n"
            f"New email:\n"
            f"  Subject: {email_subject!r}\n"
            f"  From: {email_from}\n"
            f"  Snippet: {email_snippet!r}\n\n"
            f"Candidate thread:\n"
            f"  Subject: {candidate_subject!r}\n"
            f"  Participants: {', '.join(candidate_participants)}\n"
            f"  Latest message snippet: {candidate_snippet!r}"
        )

        try:
            data, _ = await self._call_claude_tool(
                model=self.model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
                tool=THREAD_MERGE_TOOL,
            )
            if data is None:
                return {"should_merge": False, "confidence": 0.0, "reason": "no tool response"}
            return data
        except Exception as e:
            logger.error(f"Thread merge check error: {e}")
            return {"should_merge": False, "confidence": 0.0, "reason": f"Error: {e}"}

    async def generate_thread_digest(
        self,
        thread_id: str,
        account_id: int,
        user_context: Optional[str] = None,
        account_description: Optional[str] = None,
    ) -> Optional["ThreadDigest"]:
        """Analyze a thread and persist the result as a ThreadDigest row.

        Creates or updates the digest for the given gmail_thread_id.
        Only processes threads with 2+ messages.
        """
        from backend.models.ai import ThreadDigest

        async with async_session() as db:
            # Load thread emails to gather metadata
            result = await db.execute(
                select(Email).where(
                    Email.gmail_thread_id == thread_id,
                    Email.account_id == account_id,
                    Email.is_trash == False,
                    Email.is_spam == False,
                ).order_by(Email.date)
            )
            emails = result.scalars().all()

            if len(emails) < 2:
                return None

            # Gather metadata from the emails
            subject = emails[0].subject or "(no subject)"
            message_count = len(emails)
            latest_date = emails[-1].date
            participants = []
            seen_addrs = set()
            for e in emails:
                addr = e.from_address
                if addr and addr not in seen_addrs:
                    seen_addrs.add(addr)
                    participants.append({
                        "name": e.from_name or addr,
                        "address": addr,
                    })

            # Call the thread analysis
            analysis = await self.analyze_thread(
                thread_id,
                user_context=user_context,
                account_description=account_description,
            )

            if not analysis:
                logger.warning(f"Thread analysis returned None for thread {thread_id}")
                return None

            # Upsert the ThreadDigest row
            existing_result = await db.execute(
                select(ThreadDigest).where(
                    ThreadDigest.account_id == account_id,
                    ThreadDigest.gmail_thread_id == thread_id,
                )
            )
            digest = existing_result.scalar_one_or_none()

            if digest:
                digest.conversation_type = analysis.get("conversation_type", "other")
                digest.summary = analysis.get("thread_summary")
                digest.resolved_outcome = analysis.get("resolved_outcome")
                digest.is_resolved = analysis.get("is_resolved", False)
                digest.key_topics = analysis.get("key_topics", [])
                digest.message_count = message_count
                digest.participants = participants
                digest.subject = subject
                digest.latest_date = latest_date
                digest.model_used = self.model
                digest.updated_at = datetime.now(timezone.utc)
            else:
                digest = ThreadDigest(
                    account_id=account_id,
                    gmail_thread_id=thread_id,
                    conversation_type=analysis.get("conversation_type", "other"),
                    summary=analysis.get("thread_summary"),
                    resolved_outcome=analysis.get("resolved_outcome"),
                    is_resolved=analysis.get("is_resolved", False),
                    key_topics=analysis.get("key_topics", []),
                    message_count=message_count,
                    participants=participants,
                    subject=subject,
                    latest_date=latest_date,
                    model_used=self.model,
                )
                db.add(digest)

            await db.commit()
            await db.refresh(digest)
            logger.info(f"Generated thread digest for {thread_id}: type={digest.conversation_type}, resolved={digest.is_resolved}")
            return digest

    async def batch_categorize(
        self,
        email_ids: list[int],
        on_progress=None,
        user_context: Optional[str] = None,
        account_descriptions: Optional[dict[int, str]] = None,
        account_emails: Optional[dict[int, str]] = None,
    ):
        """Batch categorize emails with parallel processing.

        account_descriptions: mapping of account_id -> description for context.
        account_emails: mapping of account_id -> email address for sender identity.
        """
        sem = asyncio.Semaphore(CONCURRENCY)

        # Pre-load account_id for each email so we can look up the description/email
        acct_map: dict[int, int] = {}
        if account_descriptions or account_emails:
            async with async_session() as db:
                result = await db.execute(
                    select(Email.id, Email.account_id).where(Email.id.in_(email_ids))
                )
                for eid, aid in result.all():
                    acct_map[eid] = aid

        async def process_one(eid):
            async with sem:
                try:
                    acct_id = acct_map.get(eid)
                    acct_desc = None
                    acct_email = None
                    if account_descriptions and acct_id is not None:
                        acct_desc = account_descriptions.get(acct_id)
                    if account_emails and acct_id is not None:
                        acct_email = account_emails.get(acct_id)
                    await self.analyze_email(
                        eid,
                        user_context=user_context,
                        account_description=acct_desc,
                        account_email=acct_email,
                    )
                    if on_progress:
                        await on_progress()
                except Exception as e:
                    logger.error(f"Batch categorize error for {eid}: {e}")
                    if on_progress:
                        await on_progress()

        await asyncio.gather(*[process_one(eid) for eid in email_ids], return_exceptions=True)

    async def draft_action_reply(self, todo_id: int, user_context: Optional[str] = None) -> dict:
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

            # Build user context preamble for reply drafting
            context_preamble = ""
            if user_context:
                context_preamble = f"About the person writing this reply: {user_context}\n\nUse this context to write a reply that matches their role and tone.\n\n"

            prompt = f"""{context_preamble}You need to draft a reply to an email to address a specific action item.

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

    async def generate_custom_reply(
        self,
        email_id: int,
        user_prompt: str,
        user_context: Optional[str] = None,
        account_description: Optional[str] = None,
        account_email: Optional[str] = None,
    ) -> dict:
        """Generate a custom reply or new email based on a user-provided prompt instruction.

        Returns a dict with: body, and optionally to, cc, subject, is_new_email
        when the instruction calls for a new compose rather than a thread reply.
        """
        async with async_session() as db:
            result = await db.execute(select(Email).where(Email.id == email_id))
            email = result.scalar_one_or_none()
            if not email:
                raise ValueError(f"Email {email_id} not found")

            body = email.body_text or email.snippet or ""
            if len(body) > 5000:
                body = body[:5000] + "..."

            # Build user context preamble
            context_preamble = ""
            context_parts = []
            if account_email:
                context_parts.append(
                    f"You are drafting on behalf of {account_email}. "
                    f"Write FROM {account_email}'s perspective."
                )
            if user_context:
                context_parts.append(f"About the user: {user_context}")
            if account_description:
                context_parts.append(f"This email is from their account used for: {account_description}")
            if context_parts:
                context_preamble = "\n".join(context_parts) + "\n\n"

            # Build thread context
            thread_context = ""
            if email.gmail_thread_id:
                thread_result = await db.execute(
                    select(Email)
                    .where(
                        Email.gmail_thread_id == email.gmail_thread_id,
                        Email.account_id == email.account_id,
                        Email.id != email.id,
                    )
                    .order_by(desc(Email.date))
                    .limit(5)
                )
                thread_emails = thread_result.scalars().all()
                if thread_emails:
                    lines = []
                    for te in reversed(thread_emails):
                        direction = "[Sent by you]" if te.is_sent else "[Received]"
                        date_str = te.date.strftime("%Y-%m-%d %H:%M") if te.date else "unknown date"
                        snippet = (te.snippet or "")[:120]
                        lines.append(f"  {direction} {date_str} — {te.from_name or te.from_address}: {snippet}")
                    thread_context = (
                        "\n\nThread context (other messages in this conversation, oldest first):\n"
                        + "\n".join(lines)
                    )

            # Calendar context for scheduling-related prompts
            calendar_context = ""
            scheduling_keywords = ["meeting", "calendar", "schedule", "invite", "rsvp",
                                   "appointment", "call", "sync", "standup", "1:1",
                                   "one-on-one", "catch up", "reschedule", "availability",
                                   "later date", "another time", "postpone"]
            prompt_lower = user_prompt.lower()
            subject_lower = (email.subject or "").lower()
            body_lower = body[:500].lower()
            is_scheduling = any(
                kw in subject_lower or kw in body_lower or kw in prompt_lower
                for kw in scheduling_keywords
            )
            if is_scheduling:
                try:
                    calendar_context = await self._get_upcoming_events_context(email.account_id)
                except Exception as cal_err:
                    logger.debug(f"Could not load calendar context for custom reply: {cal_err}")

            prompt = f"""{context_preamble}{calendar_context}The email the user is currently viewing:
From: {email.from_name or ''} <{email.from_address or ''}>
To: {json.dumps(email.to_addresses or [])}
Subject: {email.subject or '(no subject)'}
Date: {email.date}
{thread_context}
Body:
{body}

User's instruction: {user_prompt}"""

            data, _ = await self._call_claude_tool(
                model=self.model,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
                tool=CUSTOM_REPLY_TOOL,
                system=CUSTOM_REPLY_SYSTEM,
            )
            if data is None:
                return {"body": "", "is_new_email": False}

            result = {"body": data.get("body", ""), "is_new_email": bool(data.get("is_new_email", False))}
            if result["is_new_email"]:
                if data.get("to"):
                    result["to"] = data["to"]
                if data.get("cc"):
                    result["cc"] = data["cc"]
                if data.get("subject"):
                    result["subject"] = data["subject"]
            return result

    # ------------------------------------------------------------------
    # Anthropic Message Batches API path (50% cheaper, async, no streaming)
    # ------------------------------------------------------------------

    # Below this size we just use the realtime asyncio fan-out — submitting,
    # polling, and downloading a Batches result is overhead that only pays
    # off for larger jobs. Above this, the 50% discount + rate-limit
    # headroom pays for itself.
    BATCH_API_MIN_SIZE = 25
    # Polling cadence and ceiling for the Batches API. Most batches finish
    # within a few minutes, but the SLA is up to 24 hours.
    _BATCH_POLL_SECONDS = 20
    _BATCH_MAX_WAIT_SECONDS = 60 * 60 * 6  # 6h ceiling

    async def batch_categorize_via_messages_batch(
        self,
        email_ids: list[int],
        on_progress=None,
        user_context: Optional[str] = None,
        account_descriptions: Optional[dict[int, str]] = None,
        account_emails: Optional[dict[int, str]] = None,
    ) -> int:
        """Categorize a list of emails via Anthropic's Message Batches API.

        - 50% cheaper than the realtime endpoint
        - Avoids per-call rate limits during large initial syncs
        - Trade-off: no per-email progress updates until the batch completes

        Returns the number of emails successfully analyzed.
        """
        if not email_ids:
            return 0

        client = self._get_client()
        api_model = base_model_id(self.model)

        # Step 1: Build per-email requests, loading context inside one session.
        unsub_by_id: dict[int, Optional[dict]] = {}
        requests: list[dict] = []
        async with async_session() as db:
            email_rows = await db.execute(
                select(Email).where(Email.id.in_(email_ids))
            )
            emails = {e.id: e for e in email_rows.scalars().all()}

            # Skip emails that already have an analysis.
            already = await db.execute(
                select(AIAnalysis.email_id).where(AIAnalysis.email_id.in_(email_ids))
            )
            already_ids = {row[0] for row in already.all()}

            for eid in email_ids:
                if eid in already_ids:
                    continue
                email = emails.get(eid)
                if not email:
                    continue

                unsub_info = None
                if email.raw_headers:
                    unsub_info = _parse_list_unsubscribe(email.raw_headers)
                unsub_by_id[eid] = unsub_info

                acct_id = email.account_id
                acct_desc = (account_descriptions or {}).get(acct_id)
                acct_email = (account_emails or {}).get(acct_id)

                prompt = await self._build_analyze_prompt(
                    email, db, user_context, acct_desc, acct_email, unsub_info,
                )

                requests.append({
                    "custom_id": f"email-{eid}",
                    "params": {
                        "model": api_model,
                        "max_tokens": 1500,
                        "system": [{
                            "type": "text",
                            "text": ANALYZE_EMAIL_SYSTEM,
                            "cache_control": {"type": "ephemeral"},
                        }],
                        "tools": [ANALYZE_EMAIL_TOOL],
                        "tool_choice": {"type": "tool", "name": ANALYZE_EMAIL_TOOL["name"]},
                        "messages": [{"role": "user", "content": prompt}],
                    },
                })

        if not requests:
            logger.info("batch_categorize_via_messages_batch: nothing to submit")
            return 0

        logger.info(
            f"Submitting {len(requests)} emails to Anthropic Message Batches API "
            f"(model={api_model})"
        )

        # Step 2: Submit the batch.
        try:
            batch = await asyncio.to_thread(
                client.messages.batches.create, requests=requests,
            )
        except Exception as e:
            logger.error(f"Batches submit failed: {e}")
            return 0

        batch_id = batch.id
        logger.info(f"Batch {batch_id} submitted; polling for completion...")

        # Step 3: Poll until ended.
        waited = 0
        while True:
            await asyncio.sleep(self._BATCH_POLL_SECONDS)
            waited += self._BATCH_POLL_SECONDS
            try:
                batch = await asyncio.to_thread(client.messages.batches.retrieve, batch_id)
            except Exception as e:
                logger.error(f"Batch {batch_id} poll failed: {e}")
                if waited >= self._BATCH_MAX_WAIT_SECONDS:
                    return 0
                continue
            status = getattr(batch, "processing_status", None)
            if status == "ended":
                break
            if waited >= self._BATCH_MAX_WAIT_SECONDS:
                logger.error(f"Batch {batch_id} did not finish within ceiling")
                return 0

        # Step 4: Download results and persist each succeeded analysis.
        analyzed = 0
        try:
            results_iter = await asyncio.to_thread(client.messages.batches.results, batch_id)
        except Exception as e:
            logger.error(f"Batch {batch_id} results fetch failed: {e}")
            return 0

        for entry in results_iter:
            custom_id = getattr(entry, "custom_id", "")
            if not custom_id.startswith("email-"):
                continue
            try:
                eid = int(custom_id.split("-", 1)[1])
            except (ValueError, IndexError):
                continue

            result = getattr(entry, "result", None)
            if result is None or getattr(result, "type", "") != "succeeded":
                logger.warning(f"Batch entry {custom_id} did not succeed: {result}")
                continue

            message = getattr(result, "message", None)
            if message is None:
                continue

            analysis_data = None
            for block in getattr(message, "content", []) or []:
                if getattr(block, "type", None) == "tool_use" and block.name == ANALYZE_EMAIL_TOOL["name"]:
                    analysis_data = block.input
                    break
            if analysis_data is None:
                logger.warning(f"Batch entry {custom_id} had no tool_use block")
                continue

            usage = getattr(message, "usage", None)
            tokens_used = ((usage.input_tokens or 0) + (usage.output_tokens or 0)) if usage else 0

            try:
                async with async_session() as db:
                    # Re-check existing inside this session in case another
                    # writer raced us between submit and persist.
                    existing = await db.scalar(
                        select(AIAnalysis).where(AIAnalysis.email_id == eid)
                    )
                    if existing:
                        continue
                    row = self._build_analysis_row(
                        eid, analysis_data, unsub_by_id.get(eid), tokens_used,
                    )
                    db.add(row)
                    await db.commit()
                    analyzed += 1
                    if on_progress:
                        await on_progress()
            except Exception as e:
                logger.error(f"Failed to persist batch result for email {eid}: {e}")

        logger.info(
            f"Batch {batch_id} complete: persisted {analyzed}/{len(requests)} analyses"
        )
        return analyzed

    async def auto_categorize_newest(
        self,
        account_id: int,
        since_date: Optional[datetime] = None,
        limit: int = None,
        on_progress=None,
        user_context: Optional[str] = None,
        account_description: Optional[str] = None,
        account_email: Optional[str] = None,
    ) -> int:
        """Categorize unanalyzed emails for an account.

        If since_date is provided, only emails on or after that date are considered.
        If limit is provided, caps the number of emails to process.
        If neither is provided, processes all unanalyzed emails.

        Uses parallel processing with a concurrency semaphore for speed.
        Returns the count of emails analyzed.
        """
        async with async_session() as db:
            # Get unanalyzed emails that don't have an AIAnalysis row
            subquery = select(AIAnalysis.email_id)
            where_clauses = [
                Email.account_id == account_id,
                ~Email.id.in_(subquery),
                Email.is_trash == False,
                Email.is_spam == False,
            ]
            if since_date is not None:
                where_clauses.append(Email.date >= since_date)

            query = select(Email.id).where(*where_clauses).order_by(desc(Email.date))
            if limit is not None:
                query = query.limit(limit)

            result = await db.execute(query)
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
                    result = await self.analyze_email(
                        eid,
                        user_context=user_context,
                        account_description=account_description,
                        account_email=account_email,
                    )
                    if result:
                        analyzed += 1
                    if on_progress:
                        await on_progress()
                except Exception as e:
                    logger.error(f"Auto-categorize error for email {eid}: {e}")
                    if on_progress:
                        await on_progress()

        await asyncio.gather(*[process_one(eid) for eid in email_ids], return_exceptions=True)

        logger.info(f"Auto-categorized {analyzed}/{len(email_ids)} emails for account {account_id}")
        return analyzed
