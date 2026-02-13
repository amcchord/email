"""Topic-based email bundling service.

Groups emails across threads (and across accounts) by shared key_topics.
Bundles are user-level: a single bundle can contain emails from multiple
Google accounts belonging to the same user.
"""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import async_session
from backend.models.email import Email
from backend.models.ai import AIAnalysis, EmailBundle
from backend.models.account import GoogleAccount
from backend.models.user import User
from backend.schemas.auth import DEFAULT_AI_PREFERENCES

logger = logging.getLogger(__name__)
settings = get_settings()

# Minimum emails required to form a bundle
MIN_BUNDLE_EMAILS = 3
# Minimum distinct threads required to form a bundle
MIN_BUNDLE_THREADS = 2
# How far back to look for emails when building bundles
BUNDLE_LOOKBACK_DAYS = 30
# Max concurrent Claude calls for bundle summarization
BUNDLE_CONCURRENCY = 3


def _normalize_topic(topic: str) -> str:
    """Normalize a topic string for comparison."""
    return topic.lower().strip()


def _cluster_topics(topic_to_emails: dict[str, list[dict]]) -> list[dict]:
    """Cluster topics that share emails into merged groups.

    Each email dict has: email_id, thread_id, account_id, subject, summary, date.

    Returns a list of clusters, each with:
        topics: set of topic strings
        emails: list of email dicts (deduplicated by email_id)
    """
    # Build adjacency: topics that share emails should merge
    # Start with each topic as its own cluster
    topic_list = list(topic_to_emails.keys())
    parent = {t: t for t in topic_list}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Build email -> topics index
    email_topics: dict[int, list[str]] = defaultdict(list)
    for topic, emails in topic_to_emails.items():
        for e in emails:
            email_topics[e["email_id"]].append(topic)

    # Union topics that share emails
    for _eid, topics in email_topics.items():
        if len(topics) > 1:
            for i in range(1, len(topics)):
                union(topics[0], topics[i])

    # Group topics by their root
    root_to_topics: dict[str, set] = defaultdict(set)
    for t in topic_list:
        root_to_topics[find(t)].add(t)

    # Build final clusters
    clusters = []
    for topics in root_to_topics.values():
        seen_ids = set()
        emails = []
        for t in topics:
            for e in topic_to_emails[t]:
                if e["email_id"] not in seen_ids:
                    seen_ids.add(e["email_id"])
                    emails.append(e)
        clusters.append({
            "topics": topics,
            "emails": emails,
        })

    return clusters


async def bundle_by_topics(
    user_id: int,
    model: Optional[str] = None,
) -> int:
    """Build or update topic bundles for a user across all their accounts.

    Returns the number of bundles created or updated.
    """
    if not model:
        model = DEFAULT_AI_PREFERENCES["agentic_model"]

    async with async_session() as db:
        # 1. Look up all account IDs for this user
        # Admin users see all accounts; regular users see only their own
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            logger.warning(f"bundle_by_topics: user {user_id} not found")
            return 0

        if user.is_admin:
            acct_result = await db.execute(
                select(GoogleAccount.id).where(GoogleAccount.is_active == True)
            )
        else:
            acct_result = await db.execute(
                select(GoogleAccount.id).where(GoogleAccount.user_id == user_id)
            )
        account_ids = [r[0] for r in acct_result.all()]

        if not account_ids:
            logger.info(f"bundle_by_topics: no accounts for user {user_id}")
            return 0

        # 2. Load recent analyzed emails with key_topics from all accounts
        since = datetime.now(timezone.utc) - timedelta(days=BUNDLE_LOOKBACK_DAYS)
        result = await db.execute(
            select(
                Email.id,
                Email.gmail_thread_id,
                Email.account_id,
                Email.subject,
                Email.date,
                AIAnalysis.summary,
                AIAnalysis.key_topics,
            )
            .join(AIAnalysis, AIAnalysis.email_id == Email.id)
            .where(
                Email.account_id.in_(account_ids),
                Email.is_trash == False,
                Email.is_spam == False,
                Email.date >= since,
                AIAnalysis.key_topics.isnot(None),
            )
            .order_by(desc(Email.date))
            .limit(1000)
        )
        rows = result.all()

        if not rows:
            logger.info(f"bundle_by_topics: no analyzed emails with topics for user {user_id}")
            return 0

        # 3. Build topic -> emails index
        topic_to_emails: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            topics = row.key_topics
            if not isinstance(topics, list):
                continue
            email_data = {
                "email_id": row.id,
                "thread_id": row.gmail_thread_id,
                "account_id": row.account_id,
                "subject": row.subject,
                "summary": row.summary,
                "date": row.date,
            }
            for topic in topics:
                if topic:
                    normalized = _normalize_topic(topic)
                    topic_to_emails[normalized].append(email_data)

        # 4. Cluster overlapping topics
        clusters = _cluster_topics(topic_to_emails)

        # 5. Filter to qualifying clusters
        qualifying = []
        for cluster in clusters:
            emails = cluster["emails"]
            if len(emails) < MIN_BUNDLE_EMAILS:
                continue
            distinct_threads = set(e["thread_id"] for e in emails)
            if len(distinct_threads) < MIN_BUNDLE_THREADS:
                continue
            qualifying.append(cluster)

        if not qualifying:
            logger.info(f"bundle_by_topics: no qualifying clusters for user {user_id}")
            return 0

        logger.info(f"bundle_by_topics: found {len(qualifying)} qualifying topic clusters for user {user_id}")

        # 6. For each cluster, generate a title/summary via Claude and upsert
        from backend.services.ai import AIService
        ai = AIService(model=model)

        sem = asyncio.Semaphore(BUNDLE_CONCURRENCY)
        bundles_created = 0

        async def process_cluster(cluster):
            nonlocal bundles_created
            async with sem:
                try:
                    bundle = await _upsert_bundle(db, ai, user_id, cluster)
                    if bundle:
                        bundles_created += 1
                except Exception as e:
                    logger.error(f"bundle_by_topics: error processing cluster: {e}")

        await asyncio.gather(
            *[process_cluster(c) for c in qualifying],
            return_exceptions=True,
        )

        # 7. Mark old bundles as stale
        await _mark_stale_bundles(db, user_id, since)

        await db.commit()
        logger.info(f"bundle_by_topics: created/updated {bundles_created} bundles for user {user_id}")
        return bundles_created


async def _upsert_bundle(
    db: AsyncSession,
    ai: "AIService",
    user_id: int,
    cluster: dict,
) -> Optional[EmailBundle]:
    """Create or update an EmailBundle from a topic cluster."""
    emails = cluster["emails"]
    topics = sorted(cluster["topics"])
    email_ids = sorted(set(e["email_id"] for e in emails))
    thread_ids = sorted(set(e["thread_id"] for e in emails if e["thread_id"]))
    acct_ids = sorted(set(e["account_id"] for e in emails))
    dates = [e["date"] for e in emails if e["date"]]
    latest_date = max(dates) if dates else None

    # Check for an existing bundle with significant topic overlap
    existing_result = await db.execute(
        select(EmailBundle).where(
            EmailBundle.user_id == user_id,
            EmailBundle.status != "stale",
        )
    )
    existing_bundles = existing_result.scalars().all()

    matched_bundle = None
    topics_set = set(topics)
    for bundle in existing_bundles:
        existing_topics = set(bundle.key_topics or [])
        overlap = topics_set & existing_topics
        # If more than half the topics overlap, consider it the same bundle
        if len(overlap) >= max(1, min(len(topics_set), len(existing_topics)) // 2):
            matched_bundle = bundle
            break

    # Generate title and summary using Claude
    title, summary = await _generate_bundle_summary(ai, topics, emails)

    if matched_bundle:
        matched_bundle.title = title
        matched_bundle.summary = summary
        matched_bundle.key_topics = topics
        matched_bundle.email_ids = email_ids
        matched_bundle.thread_ids = thread_ids
        matched_bundle.account_ids = acct_ids
        matched_bundle.email_count = len(email_ids)
        matched_bundle.thread_count = len(thread_ids)
        matched_bundle.latest_date = latest_date
        matched_bundle.status = "active"
        matched_bundle.updated_at = datetime.now(timezone.utc)
        return matched_bundle
    else:
        bundle = EmailBundle(
            user_id=user_id,
            title=title,
            summary=summary,
            key_topics=topics,
            email_ids=email_ids,
            thread_ids=thread_ids,
            account_ids=acct_ids,
            email_count=len(email_ids),
            thread_count=len(thread_ids),
            latest_date=latest_date,
            status="active",
        )
        db.add(bundle)
        return bundle


async def _generate_bundle_summary(
    ai: "AIService",
    topics: list[str],
    emails: list[dict],
) -> tuple[str, str]:
    """Use Claude to generate a concise title and summary for a bundle."""
    # Build a compact representation of the bundle contents
    email_lines = []
    for e in emails[:15]:  # Limit to 15 emails for prompt size
        subject = e.get("subject") or "(no subject)"
        summary = e.get("summary") or ""
        date_str = ""
        if e.get("date"):
            date_str = e["date"].strftime("%Y-%m-%d")
        email_lines.append(f"  - [{date_str}] {subject}: {summary}")

    emails_text = "\n".join(email_lines)

    prompt = f"""You are grouping related emails by topic. Given the following topics and email summaries, generate a concise title and 1-2 sentence summary for this group.

Topics: {', '.join(topics)}

Emails in this group:
{emails_text}

Respond with ONLY valid JSON:
{{
    "title": "<short descriptive title for this email group, 3-8 words>",
    "summary": "<1-2 sentence summary of what this group of emails is about and any key outcomes>"
}}"""

    try:
        response = await ai._call_claude(
            model=ai.model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = response.content[0].text.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        data = json.loads(response_text)
        return data.get("title", "Email Group"), data.get("summary", "")
    except Exception as e:
        logger.error(f"Failed to generate bundle summary: {e}")
        # Fallback: use the topics as title
        title = ", ".join(topics[:3])
        if len(topics) > 3:
            title += f" +{len(topics) - 3} more"
        return title.title(), f"{len(emails)} emails across {len(set(e['thread_id'] for e in emails))} threads"


async def _mark_stale_bundles(
    db: AsyncSession,
    user_id: int,
    cutoff: datetime,
) -> None:
    """Mark bundles as stale if their latest email is older than the cutoff."""
    result = await db.execute(
        select(EmailBundle).where(
            EmailBundle.user_id == user_id,
            EmailBundle.status == "active",
            EmailBundle.latest_date < cutoff,
        )
    )
    stale_bundles = result.scalars().all()
    for bundle in stale_bundles:
        bundle.status = "stale"
        bundle.updated_at = datetime.now(timezone.utc)

    if stale_bundles:
        logger.info(f"Marked {len(stale_bundles)} bundles as stale for user {user_id}")
