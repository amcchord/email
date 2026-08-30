from backend.services.gmail import GmailService


def test_parse_message_preserves_quoted_commas_and_address_groups():
    parsed = GmailService.parse_message({
        "id": "generated-message",
        "threadId": "generated-thread",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": '"Doe, Jane" <jane@example.test>'},
                {
                    "name": "To",
                    "value": 'Reviewers: "Smith, John" <john@example.test>, teammate@example.test;',
                },
                {"name": "Cc", "value": '"Observer, One" <observer@example.test>'},
            ],
            "parts": [],
        },
    })

    assert parsed["from_name"] == "Doe, Jane"
    assert parsed["from_address"] == "jane@example.test"
    assert parsed["to_addresses"] == [
        {"name": "Smith, John", "address": "john@example.test"},
        {"name": "", "address": "teammate@example.test"},
    ]
    assert parsed["cc_addresses"] == [
        {"name": "Observer, One", "address": "observer@example.test"},
    ]
