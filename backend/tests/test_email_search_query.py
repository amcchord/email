from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from backend.models.email import Email
from backend.routers.emails import jsonb_contains, list_emails
from backend.services.email_search_query import (
    SearchAccount,
    SearchLabel,
    SearchQueryError,
    build_email_search_clause,
    parse_email_search,
)


ACCOUNTS = (
    SearchAccount(
        id=7,
        email="qa.primary@example.test",
        display_name="Primary QA",
        description="Launch testing",
        short_label="Primary",
    ),
    SearchAccount(
        id=8,
        email="qa.secondary@example.test",
        display_name="Secondary QA",
        description="Launch archive",
        short_label="Secondary",
    ),
)
LABELS = (
    SearchLabel(account_id=7, gmail_label_id="Label_7", name="Team / Q3"),
    SearchLabel(account_id=8, gmail_label_id="Label_8", name="Team / Q3"),
)


class _AccountResult:
    def all(self):
        return [SimpleNamespace(
            id=7,
            email="qa.primary@example.test",
            display_name="Primary QA",
            description="Generated account",
            short_label="Primary",
        )]


class _AccountOnlySession:
    async def execute(self, _statement):
        return _AccountResult()


def _compiled(query: str, *, timezone_name: str = "America/New_York"):
    parsed = parse_email_search(query)
    clause = build_email_search_clause(
        parsed,
        accounts=ACCOUNTS,
        labels=LABELS,
        timezone_name=timezone_name,
    )
    statement = select(Email.id).where(Email.account_id.in_([7, 8]), clause)
    return statement.compile(dialect=postgresql.dialect())


def test_parses_composable_operators_quotes_negation_and_or():
    parsed = parse_email_search(
        'from:renee+launch@example.test subject:"Quarterly & Planning" '
        'has:attachment -is:read in:inbox OR "ticket:1234"'
    )

    assert len(parsed.groups) == 2
    assert parsed.has_positive_in is True
    assert [clause.operator for clause in parsed.groups[0].clauses] == [
        "from", "subject", "has", "is", "in"
    ]
    assert parsed.groups[0].clauses[1].quoted is True
    assert parsed.groups[0].clauses[3].negated is True
    assert parsed.groups[1].clauses[0].operator is None
    assert parsed.groups[1].clauses[0].value == "ticket:1234"
    assert parsed.groups[1].clauses[0].quoted is True


def test_unknown_colon_tokens_remain_plain_text():
    parsed = parse_email_search("ticket:1234 https://example.test")

    assert [clause.operator for clause in parsed.clauses] == [None, None]
    assert [clause.value for clause in parsed.clauses] == [
        "ticket:1234", "https://example.test"
    ]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ('subject:"unfinished', "unterminated quote"),
        ('"unfinished\\', "dangling escape"),
        ("subject:", "requires a value"),
        ("OR subject:launch", "both sides"),
        ("subject:launch OR", "both sides"),
        ("subject:launch OR OR from:renee", "both sides"),
        ("is:maybe", "is: must be one of"),
        ("has:calendar", "currently supports attachment"),
        ("in:moon", "in: must be one of"),
        ("after:2026-02-30", "valid date"),
        ("after:2026-2-3", "valid date"),
        ("(subject:launch)", "Parentheses"),
        ('""', "requires a value"),
        ('body:""', "requires a value"),
        ("-", "after"),
        ("--from:renee", "only one leading"),
        ('foo:"bar baz"', "supported search operator"),
    ],
)
def test_rejects_invalid_syntax_with_stable_detail(query, message):
    with pytest.raises(SearchQueryError, match=message):
        parse_email_search(query)


def test_enforces_length_and_clause_limits():
    with pytest.raises(SearchQueryError, match="512 characters"):
        parse_email_search("x" * 513)
    with pytest.raises(SearchQueryError, match="32 clauses"):
        parse_email_search(" ".join(f"term{i}" for i in range(33)))
    with pytest.raises(SearchQueryError, match="256 characters"):
        parse_email_search("subject:" + "x" * 257)


def test_compiles_user_values_as_bound_parameters():
    malicious = "x%' OR true --"
    compiled = _compiled(f'label:"{malicious}" OR subject:"100%_launch"')
    sql = str(compiled)

    assert malicious not in sql
    assert "100%_launch" not in sql
    assert "emails.account_id IN" in sql
    assert any(value == [7, 8] for value in compiled.params.values())
    assert any(value == "%100\\%\\_launch%" for value in compiled.params.values())


def test_recipient_filters_expand_arrays_and_search_only_values():
    malicious = "address%' OR true --"
    compiled = _compiled(
        f'to:"{malicious}" cc:"Launch Person" bcc:legacy@example.test'
    )
    sql = str(compiled)

    assert malicious not in sql
    assert sql.count("jsonb_array_elements") == 3
    assert "->>" in sql
    assert "jsonb_typeof" in sql
    assert any(
        value == "%address\\%' OR true --%"
        for value in compiled.params.values()
    )


def test_safe_jsonb_helper_binds_malicious_values():
    malicious = 'INBOX"]} OR true --'
    compiled = select(Email.id).where(jsonb_contains(Email.labels, malicious)).compile(
        dialect=postgresql.dialect()
    )

    assert malicious not in str(compiled)
    assert [malicious] in compiled.params.values()


def test_label_matches_are_isolated_per_owned_account():
    compiled = _compiled('account:qa.primary@example.test label:"Team / Q3"')
    sql = str(compiled)

    assert "emails.account_id IN" in sql
    assert {"Label_7", "Label_8"}.issubset({
        item
        for value in compiled.params.values()
        if isinstance(value, list)
        for item in value
    })


def test_date_boundaries_use_requested_zone_and_half_open_comparisons():
    compiled = _compiled("after:2026-03-08 before:2026-03-09")
    boundaries = [value for value in compiled.params.values() if isinstance(value, datetime)]

    assert boundaries == [
        datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 9, 4, 0, tzinfo=timezone.utc),
    ]
    assert "emails.date >=" in str(compiled)
    assert "emails.date <" in str(compiled)


def test_unknown_timezone_is_rejected():
    with pytest.raises(SearchQueryError, match="Unknown time zone"):
        _compiled("after:2026-03-08", timezone_name="Mars/Olympus_Mons")


def test_or_branch_without_in_stays_out_of_spam_and_trash():
    compiled = _compiled("in:trash OR from:renee@example.test")
    sql = str(compiled)

    assert "emails.is_trash IS true" in sql
    assert "emails.is_trash IS false" in sql
    assert "emails.is_spam IS false" in sql


def test_null_safe_negation_uses_coalesce():
    compiled = _compiled("-from:renee@example.test -body:launch")

    assert str(compiled).lower().count("coalesce") >= 4


@pytest.mark.asyncio
async def test_foreign_outer_account_fails_closed_before_email_query():
    with pytest.raises(HTTPException) as error:
        await list_emails(
            account_id=999,
            db=_AccountOnlySession(),
            user=SimpleNamespace(id=42),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Account not found"


@pytest.mark.asyncio
async def test_route_search_syntax_errors_have_string_422_details():
    with pytest.raises(HTTPException) as error:
        await list_emails(
            search="is:maybe",
            db=_AccountOnlySession(),
            user=SimpleNamespace(id=42),
        )

    assert error.value.status_code == 422
    assert isinstance(error.value.detail, str)
    assert error.value.detail.startswith("is: must be one of")
