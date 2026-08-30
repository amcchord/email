from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.routers.emails import get_email, get_thread


class FakeResult:
    def __init__(self, *, scalar=None, rows=None, values=None):
        self.scalar = scalar
        self.rows = list(rows or [])
        self.values = list(values or [])

    def scalar_one_or_none(self):
        return self.scalar

    def all(self):
        return self.rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self.values)


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("Unexpected database query")
        return self.results.pop(0)


def generated_email(*, email_id: int, account_id: int, thread_id: str = "thread-generated"):
    return SimpleNamespace(
        id=email_id,
        account_id=account_id,
        gmail_message_id=f"message-{email_id}",
        gmail_thread_id=thread_id,
        subject=f"Generated subject {email_id}",
        from_address=f"sender-{email_id}@example.test",
        from_name=f"Sender {email_id}",
        to_addresses=[{"name": "Recipient", "address": "recipient@example.test"}],
        cc_addresses=[],
        bcc_addresses=[],
        date=None,
        snippet="Generated snippet",
        body_text="Generated body",
        body_html="<p>Generated body</p>",
        is_read=False,
        is_starred=False,
        is_draft=False,
        is_sent=False,
        is_trash=False,
        is_spam=False,
        has_attachments=False,
        labels=["INBOX"],
        size_bytes=128,
        reply_to=None,
        message_id_header=f"<message-{email_id}@example.test>",
        in_reply_to=None,
        references_header=f"<ancestor-{email_id}@example.test>",
        attachments=[],
        ai_analysis=None,
    )


@pytest.mark.asyncio
async def test_get_email_returns_exact_owned_account_identity():
    email = generated_email(email_id=101, account_id=17)
    account = SimpleNamespace(id=17, user_id=23, email="source-account@example.test")
    db = FakeSession(
        FakeResult(scalar=email),
        FakeResult(scalar=account),
    )

    response = await get_email(
        email_id=email.id,
        db=db,
        user=SimpleNamespace(id=account.user_id),
    )

    assert response.account_id == account.id
    assert response.account_email == account.email
    assert db.results == []


@pytest.mark.asyncio
async def test_get_email_keeps_foreign_account_indistinguishable_from_missing():
    email = generated_email(email_id=102, account_id=91)
    db = FakeSession(
        FakeResult(scalar=email),
        FakeResult(scalar=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_email(
            email_id=email.id,
            db=db,
            user=SimpleNamespace(id=23),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Email not found"


@pytest.mark.asyncio
async def test_get_thread_requires_account_scope_when_provider_thread_collides():
    first = generated_email(email_id=201, account_id=17)
    second = generated_email(email_id=202, account_id=29)
    db = FakeSession(
        FakeResult(rows=[
            (17, "first-account@example.test"),
            (29, "second-account@example.test"),
        ]),
        FakeResult(values=[first, second]),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_thread(
            thread_id="thread-generated",
            order="asc",
            account_id=None,
            db=db,
            user=SimpleNamespace(id=23),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Account scope is required for this conversation"
    assert db.results == []


@pytest.mark.asyncio
async def test_get_thread_preserves_unique_account_legacy_lookup():
    first = generated_email(email_id=201, account_id=17)
    second = generated_email(email_id=202, account_id=17)
    db = FakeSession(
        FakeResult(rows=[(17, "first-account@example.test")]),
        FakeResult(values=[first, second]),
    )

    response = await get_thread(
        thread_id="thread-generated",
        order="asc",
        account_id=None,
        db=db,
        user=SimpleNamespace(id=23),
    )

    assert [email.account_id for email in response.emails] == [17, 17]
    assert all(email.account_email == "first-account@example.test" for email in response.emails)


@pytest.mark.asyncio
async def test_get_thread_keeps_unowned_or_missing_thread_as_404():
    db = FakeSession(
        FakeResult(rows=[(17, "owned-account@example.test")]),
        FakeResult(values=[]),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_thread(
            thread_id="unavailable-thread",
            order="asc",
            db=db,
            user=SimpleNamespace(id=23),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Thread not found"


@pytest.mark.asyncio
async def test_get_thread_scopes_same_thread_id_to_requested_owned_account():
    exact = generated_email(email_id=203, account_id=29)
    db = FakeSession(
        FakeResult(rows=[(29, "exact-account@example.test")]),
        FakeResult(values=[exact]),
    )

    response = await get_thread(
        thread_id="thread-generated",
        order="desc",
        account_id=29,
        db=db,
        user=SimpleNamespace(id=23),
    )

    assert [email.account_id for email in response.emails] == [29]
    assert response.emails[0].references_header == "<ancestor-203@example.test>"
    assert db.results == []


@pytest.mark.asyncio
async def test_get_thread_rejects_unowned_account_scope_before_email_query():
    db = FakeSession(FakeResult(rows=[]))

    with pytest.raises(HTTPException) as exc_info:
        await get_thread(
            thread_id="thread-generated",
            order="asc",
            account_id=999,
            db=db,
            user=SimpleNamespace(id=23),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Thread not found"
    assert db.results == []
