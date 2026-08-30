import base64
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

import backend.routers.compose as compose_router
from backend.schemas.email import ComposeDraftRequest
from backend.services.gmail import GmailService


def _service():
    return GmailService(SimpleNamespace(email="sender@example.com"))


def test_compose_message_builds_mixed_mime_with_attachment():
    message = _service()._build_compose_message(
        to=["recipient@example.com"],
        subject="Quarterly notes",
        body_text="Plain version",
        body_html="<p>HTML version</p>",
        attachments=[{
            "filename": "notes.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"attached content").decode(),
        }],
    )

    assert message.get_content_subtype() == "mixed"
    assert message["From"] == "sender@example.com"
    assert message["To"] == "recipient@example.com"
    parts = message.get_payload()
    assert parts[0].get_content_subtype() == "alternative"
    assert parts[1].get_filename() == "notes.txt"
    assert parts[1].get_payload(decode=True) == b"attached content"


def test_compose_message_rejects_invalid_attachment_data():
    with pytest.raises(ValueError, match="not valid base64"):
        _service()._build_compose_message(
            to=["recipient@example.com"],
            attachments=[{
                "filename": "broken.bin",
                "content_type": "application/octet-stream",
                "data_base64": "not base64!!",
            }],
        )


def test_compose_message_strips_header_newlines():
    message = _service()._build_compose_message(
        to=["recipient@example.com"],
        subject="Hello\r\nBcc: injected@example.com",
    )

    assert "\n" not in str(message["Subject"])
    assert message["Bcc"] is None


class _DraftCreateCapture:
    def __init__(self):
        self.body = None

    def users(self):
        return self

    def drafts(self):
        return self

    def create(self, *, userId, body):
        assert userId == "me"
        self.body = body
        return SimpleNamespace()


@pytest.mark.asyncio
async def test_create_draft_keeps_reply_headers_and_gmail_thread(monkeypatch):
    service = _service()
    capture = _DraftCreateCapture()

    async def execute(_request, *, context):
        assert context == "create_draft"
        return {"id": "generated-draft-id"}

    monkeypatch.setattr(service, "_get_service", lambda: capture)
    monkeypatch.setattr(service, "_execute_with_retry", execute)

    draft_id = await service.create_draft(
        to=["recipient@example.test"],
        subject="Re: Generated thread",
        body_html="<p>Generated reply</p>",
        thread_id="generated-thread-id",
        in_reply_to="<generated-parent@example.test>",
        references="<generated-root@example.test> <generated-parent@example.test>",
    )

    assert draft_id == "generated-draft-id"
    assert capture.body["message"]["threadId"] == "generated-thread-id"
    raw_message = base64.urlsafe_b64decode(capture.body["message"]["raw"])
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    assert message["In-Reply-To"] == "<generated-parent@example.test>"
    assert message["References"] == (
        "<generated-root@example.test> <generated-parent@example.test>"
    )


class _RouteResult:
    def __init__(self, account):
        self.account = account

    def scalar_one_or_none(self):
        return self.account


class _RouteDb:
    def __init__(self, account):
        self.account = account

    async def execute(self, _statement):
        return _RouteResult(self.account)


@pytest.mark.asyncio
async def test_save_draft_forwards_reply_headers_to_gmail_service(monkeypatch):
    captured = {}
    account = SimpleNamespace(
        id=17,
        user_id=23,
        email="sender@example.test",
    )

    class FakeGmailService:
        def __init__(self, account_arg, *, client_id, client_secret):
            assert account_arg is account
            assert (client_id, client_secret) == ("generated-client", "generated-secret")

        async def create_draft(self, **kwargs):
            captured.update(kwargs)
            return "generated-draft-id"

    async def fake_google_credentials(_db):
        return "generated-client", "generated-secret"

    monkeypatch.setattr(compose_router, "GmailService", FakeGmailService)
    monkeypatch.setattr(
        compose_router,
        "get_google_credentials",
        fake_google_credentials,
    )

    response = await compose_router.save_draft(
        request=ComposeDraftRequest(
            account_id=account.id,
            to=["recipient@example.test"],
            subject="Re: Generated thread",
            body_html="<p>Generated reply</p>",
            in_reply_to="<generated-parent@example.test>",
            references=(
                "<generated-root@example.test> <generated-parent@example.test>"
            ),
            thread_id="generated-thread-id",
        ),
        db=_RouteDb(account),
        user=SimpleNamespace(id=account.user_id),
    )

    assert response == {
        "message": "Draft saved",
        "draft_id": "generated-draft-id",
    }
    assert captured["in_reply_to"] == "<generated-parent@example.test>"
    assert captured["references"] == (
        "<generated-root@example.test> <generated-parent@example.test>"
    )
    assert captured["thread_id"] == "generated-thread-id"
