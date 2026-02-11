import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, text
from backend.models.email import Email
from backend.models.account import GoogleAccount

logger = logging.getLogger(__name__)


class SearchService:
    @staticmethod
    async def search_emails(
        db: AsyncSession,
        user_id: int,
        query: str,
        account_id: int = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Email], int]:
        """Full-text search across emails."""
        # Get user's accounts
        acct_result = await db.execute(
            select(GoogleAccount.id).where(GoogleAccount.user_id == user_id)
        )
        account_ids = [r[0] for r in acct_result.all()]

        if not account_ids:
            return [], 0

        ts_query = func.plainto_tsquery("english", query)

        base_query = select(Email).where(
            Email.account_id.in_(account_ids),
            Email.search_vector.op("@@")(ts_query),
        )

        if account_id and account_id in account_ids:
            base_query = base_query.where(Email.account_id == account_id)

        # Count
        count_q = select(func.count()).select_from(base_query.subquery())
        total = await db.scalar(count_q)

        # Rank and paginate
        rank = func.ts_rank(Email.search_vector, ts_query)
        results_query = base_query.order_by(desc(rank)).offset(
            (page - 1) * page_size
        ).limit(page_size)

        result = await db.execute(results_query)
        emails = result.scalars().all()

        return emails, total

    @staticmethod
    async def rebuild_search_index(db: AsyncSession, account_id: int = None):
        """Rebuild search vectors for all emails."""
        where_clause = ""
        params = {}
        if account_id:
            where_clause = "WHERE account_id = :account_id"
            params["account_id"] = account_id

        await db.execute(text(f"""
            UPDATE emails SET search_vector =
                setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(from_name, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(from_address, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(snippet, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(left(body_text, 10000), '')), 'D')
            {where_clause}
        """), params)
        await db.commit()
