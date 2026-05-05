"""Backfill emails.date for rows where the Date header was missing or set to a
Y2038-overflow value, then recompute thread_digests.latest_date for any digest
that is NULL or set to a 2038+ date.

This is the data-migration counterpart to the parser fix in
backend/services/gmail.py: chat-archive (Hangouts) messages have no Date
header, so before the fix their `Email.date` was stored as NULL. A handful of
spam senders also produce Date headers that parse to 2038-01-19 03:14:07Z
(signed-int32 overflow), which sorts ahead of every real recent thread.

Strategy:
  1. For each affected email, fetch Gmail's `internalDate` via the messages.get
     API (format=metadata is cheap) and update emails.date.
  2. Recompute thread_digests.latest_date as MAX(emails.date) over the digest's
     constituent emails for every digest where latest_date IS NULL or
     latest_date >= 2038-01-01.

The script is idempotent — it only operates on rows that still match the
"needs fix" criteria, so it can be re-run safely with no side effects when
nothing is left to do.

Usage:
    cd /opt/mail
    venv/bin/python -m scripts.backfill_email_dates [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update, func, or_

from backend.database import async_session
from backend.models.account import GoogleAccount
from backend.models.ai import ThreadDigest
from backend.models.email import Email
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService

logger = logging.getLogger("backfill_email_dates")

Y2038_THRESHOLD = datetime(2038, 1, 1, tzinfo=timezone.utc)


def _date_from_internal(internal_date: str | int | None) -> datetime | None:
    if not internal_date:
        return None
    try:
        return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


async def _fetch_internal_date(gmail: GmailService, gmail_message_id: str) -> datetime | None:
    """Fetch internalDate for a single message via the metadata-only endpoint."""
    try:
        msg = await gmail.get_message(gmail_message_id, format_type="metadata")
    except Exception as exc:
        logger.warning(
            "Failed to fetch message %s: %s", gmail_message_id, exc
        )
        return None
    return _date_from_internal(msg.get("internalDate"))


async def _backfill_emails(dry_run: bool, limit: int | None) -> tuple[int, int, set[tuple[str, int]]]:
    """Update emails with NULL or Y2038-overflow dates.

    Returns (fixed_count, skipped_count, affected_thread_account_pairs).
    """
    fixed = 0
    skipped = 0
    affected: set[tuple[str, int]] = set()

    async with async_session() as db:
        client_id, client_secret = await get_google_credentials(db)

        accounts_result = await db.execute(select(GoogleAccount))
        accounts = {a.id: a for a in accounts_result.scalars().all()}

    if not accounts:
        logger.info("No Google accounts found; nothing to backfill.")
        return fixed, skipped, affected

    gmail_clients: dict[int, GmailService] = {}

    for account_id, account in accounts.items():
        async with async_session() as db:
            stmt = (
                select(Email.id, Email.gmail_message_id, Email.gmail_thread_id, Email.account_id)
                .where(
                    Email.account_id == account_id,
                    Email.gmail_message_id.isnot(None),
                    or_(Email.date.is_(None), Email.date >= Y2038_THRESHOLD),
                )
                .order_by(Email.id)
            )
            if limit:
                stmt = stmt.limit(limit)
            rows = (await db.execute(stmt)).all()

        if not rows:
            continue

        logger.info("Account %s (id=%s): %d emails to backfill", account.email, account_id, len(rows))

        if account_id not in gmail_clients:
            gmail_clients[account_id] = GmailService(
                account, client_id=client_id, client_secret=client_secret
            )
        gmail = gmail_clients[account_id]

        for row in rows:
            internal = await _fetch_internal_date(gmail, row.gmail_message_id)
            if internal is None:
                skipped += 1
                continue

            if internal >= Y2038_THRESHOLD:
                # Even Gmail's internalDate looks bogus (rare, but possible
                # for spoofed messages). Leave it alone rather than store a
                # date that will resurface this bug.
                logger.warning(
                    "Email id=%s has internalDate >= 2038 (%s); skipping",
                    row.id, internal,
                )
                skipped += 1
                continue

            if dry_run:
                fixed += 1
                if row.gmail_thread_id:
                    affected.add((row.gmail_thread_id, row.account_id))
                continue

            async with async_session() as db:
                await db.execute(
                    update(Email).where(Email.id == row.id).values(date=internal)
                )
                await db.commit()
            fixed += 1
            if row.gmail_thread_id:
                affected.add((row.gmail_thread_id, row.account_id))

        # Reset the per-row limit so other accounts also get processed when
        # --limit is provided.
        if limit and len(rows) >= limit:
            break

    return fixed, skipped, affected


async def _recompute_digests(
    dry_run: bool,
    extra_pairs: set[tuple[str, int]] | None = None,
) -> int:
    """Recompute ThreadDigest.latest_date from the underlying emails.

    Targets:
      - digests with NULL latest_date
      - digests with latest_date >= 2038-01-01
      - digests in `extra_pairs` (threads we just touched in step 1)

    Returns the number of digests updated.
    """
    updated = 0

    async with async_session() as db:
        digest_stmt = select(ThreadDigest).where(
            or_(
                ThreadDigest.latest_date.is_(None),
                ThreadDigest.latest_date >= Y2038_THRESHOLD,
            )
        )
        digests = list((await db.execute(digest_stmt)).scalars().all())

        if extra_pairs:
            existing_keys = {(d.gmail_thread_id, d.account_id) for d in digests}
            extra_keys = [p for p in extra_pairs if p not in existing_keys]
            if extra_keys:
                # Look these up explicitly so we don't miss any digest whose
                # latest_date already had a non-NULL pre-2038 value but is
                # still stale because we just bumped the source emails.
                for thread_id, account_id in extra_keys:
                    extra = (
                        await db.execute(
                            select(ThreadDigest).where(
                                ThreadDigest.gmail_thread_id == thread_id,
                                ThreadDigest.account_id == account_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if extra is not None:
                        digests.append(extra)

        for digest in digests:
            new_latest = await db.scalar(
                select(func.max(Email.date)).where(
                    Email.gmail_thread_id == digest.gmail_thread_id,
                    Email.account_id == digest.account_id,
                    Email.date.isnot(None),
                    Email.date < Y2038_THRESHOLD,
                )
            )

            if new_latest == digest.latest_date:
                continue

            logger.info(
                "Digest id=%s thread=%s: %s -> %s",
                digest.id, digest.gmail_thread_id, digest.latest_date, new_latest,
            )

            if not dry_run:
                digest.latest_date = new_latest

            updated += 1

        if not dry_run:
            await db.commit()

    return updated


async def _main_async(dry_run: bool, limit: int | None) -> None:
    logger.info("Starting backfill (dry_run=%s, limit=%s)", dry_run, limit)

    fixed, skipped, affected = await _backfill_emails(dry_run=dry_run, limit=limit)
    logger.info(
        "Email backfill: fixed=%d skipped=%d affected_threads=%d",
        fixed, skipped, len(affected),
    )

    updated_digests = await _recompute_digests(dry_run=dry_run, extra_pairs=affected)
    logger.info("Digest recomputation: updated=%d", updated_digests)

    if dry_run:
        logger.info("Dry run complete; no changes written.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N emails per account (useful for testing).",
    )
    args = parser.parse_args()

    asyncio.run(_main_async(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
