from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.account import GoogleAccount, SyncStatus
from backend.routers.accounts import get_sync_status


class AsyncSessionAdapter:
    """Expose the async execute interface over an isolated SQLite session."""

    def __init__(self, session: Session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)


@pytest.fixture
def account_session():
    engine = create_engine("sqlite://")
    GoogleAccount.__table__.create(engine)
    SyncStatus.__table__.create(engine)

    with Session(engine) as session:
        owned = GoogleAccount(user_id=10, email="owned@example.test")
        foreign = GoogleAccount(user_id=20, email="foreign@example.test")
        session.add_all([owned, foreign])
        session.flush()
        session.add_all([
            SyncStatus(account_id=owned.id, status="completed", messages_synced=7),
            SyncStatus(account_id=foreign.id, status="error", error_message="private detail"),
        ])
        session.commit()
        yield session, owned.id, foreign.id


@pytest.mark.asyncio
async def test_get_sync_status_returns_owned_account_status(account_session):
    session, owned_id, _ = account_session

    response = await get_sync_status(
        owned_id,
        db=AsyncSessionAdapter(session),
        user=SimpleNamespace(id=10),
    )

    assert response.status == "completed"
    assert response.messages_synced == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("account_id_kind", ["foreign", "missing"])
async def test_get_sync_status_hides_unavailable_account_ids(
    account_session,
    account_id_kind,
):
    session, _, foreign_id = account_session
    account_id = foreign_id if account_id_kind == "foreign" else foreign_id + 1000

    with pytest.raises(HTTPException) as exc_info:
        await get_sync_status(
            account_id,
            db=AsyncSessionAdapter(session),
            user=SimpleNamespace(id=10),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Account not found"
