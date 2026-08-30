from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from backend.models.ai import AIAnalysis
from backend.models.email import Email
from backend.services.workflow_context import (
    SCHEDULING_ASSISTANT,
    address_is_present,
    apply_workflow_routing,
    delegated_scheduling_sql,
    normalize_address,
    workflow_context_for_message,
)


def _email(*, sender="person@example.com", to=None, cc=None):
    return SimpleNamespace(
        from_address=sender,
        to_addresses=to or [],
        cc_addresses=cc or [],
    )


def _analysis(**overrides):
    result = {
        "category": "awaiting_reply",
        "conversation_type": "scheduling",
        "priority": 1,
        "needs_reply": True,
        "is_subscription": False,
        "suggested_reply": "I am free Tuesday.",
        "reply_options": [
            {"label": "Accept", "intent": "accept", "body": "Tuesday works for me."},
        ],
        "context": {"requires_action": True},
    }
    result.update(overrides)
    return result


def test_normalize_address_handles_gmail_json_and_header_text():
    assert normalize_address({"name": "Andrea Durbin", "address": "ANDREA@mcchord.net"}) == SCHEDULING_ASSISTANT.email
    assert normalize_address("Andrea Durbin <andrea@mcchord.net>") == SCHEDULING_ASSISTANT.email
    assert address_is_present([{"address": "andrea@mcchord.net"}], SCHEDULING_ASSISTANT.email)


def test_message_context_calls_out_andrea_on_cc_and_angie_as_trusted():
    email = _email(
        sender="angie@mcchord.net",
        cc=[{"name": "Andrea Durbin", "address": "andrea@mcchord.net"}],
    )

    context = workflow_context_for_message(email)

    assert "Andrea is CC'd" in context
    assert "trusted colleague Angie Mecham" in context
    assert "do not put it in Austin's reply queue" in context


def test_routine_scheduling_with_andrea_cced_is_not_austin_followup():
    email = _email(cc=[{"address": "andrea@mcchord.net"}])

    routed = apply_workflow_routing(email, _analysis())

    assert routed["needs_reply"] is False
    assert routed["category"] == "fyi"
    assert routed["priority"] == 1
    assert routed["suggested_reply"] is None
    assert routed["reply_options"] is None
    assert routed["action_items"] == []
    assert routed["context"]["requires_action"] is False
    assert "delegated to Andrea" in routed["context"]["workflow_routing"]


def test_high_priority_scheduling_stays_visible_but_defaults_to_andrea():
    email = _email(cc=[{"address": "andrea@mcchord.net"}])

    routed = apply_workflow_routing(email, _analysis(priority=2, category="urgent"))

    assert routed["needs_reply"] is True
    assert routed["priority"] == 2
    assert routed["reply_options"][0]["label"] == "Andrea to coordinate"
    assert "Andrea is copied" in routed["reply_options"][0]["body"]


def test_scheduling_without_andrea_defaults_to_handoff_reply():
    routed = apply_workflow_routing(_email(), _analysis(priority=1))

    assert routed["reply_options"][0]["label"] == "Andrea to coordinate"
    assert "andrea@mcchord.net" in routed["reply_options"][0]["body"]
    assert routed["suggested_reply"] == routed["reply_options"][0]["body"]


def test_direct_scheduling_question_from_andrea_is_not_handed_back_to_her():
    routed = apply_workflow_routing(
        _email(sender="andrea@mcchord.net"),
        _analysis(priority=2),
    )

    assert routed["needs_reply"] is True
    assert routed["reply_options"][0]["label"] == "Accept"
    assert "coordinate with her" not in routed["suggested_reply"]


def test_angie_is_never_left_classified_as_cold_outreach():
    routed = apply_workflow_routing(
        _email(sender="Angie Mecham <angie@mcchord.net>"),
        _analysis(
            conversation_type="discussion",
            category="can_ignore",
            priority=0,
            needs_reply=False,
            is_subscription=True,
        ),
    )

    assert routed["is_subscription"] is False
    assert routed["category"] == "fyi"
    assert routed["priority"] == 1


def test_delegated_scheduling_sql_targets_to_and_cc_json():
    predicate = delegated_scheduling_sql(
        AIAnalysis.conversation_type,
        Email.to_addresses,
        Email.cc_addresses,
    )

    sql = str(
        predicate.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ILIKE" in sql
    assert "emails.to_addresses" in sql
    assert "emails.cc_addresses" in sql
    assert "andrea@mcchord.net" in sql
