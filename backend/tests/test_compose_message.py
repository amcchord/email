import base64
from types import SimpleNamespace

import pytest

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
