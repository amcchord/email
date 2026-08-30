"""Owner-specific mail workflow relationships and deterministic routing rules.

The mail client is Austin's working inbox, so important working relationships
belong in structured code rather than being left to an LLM to infer from a
free-form ``about_me`` paragraph.  Prompt context handles nuance; the small
deterministic layer prevents delegated scheduling mail from repeatedly landing
in Austin's own follow-up queue.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any, Iterable, Mapping

from sqlalchemy import Text, and_, cast, func, or_


@dataclass(frozen=True)
class WorkflowContact:
    name: str
    email: str
    relationship: str


SCHEDULING_ASSISTANT = WorkflowContact(
    name="Andrea Durbin",
    email="andrea@mcchord.net",
    relationship="Austin's assistant and the default owner of scheduling",
)

CLOSE_COLLEAGUES: tuple[WorkflowContact, ...] = (
    WorkflowContact(
        name="Angie Mecham",
        email="angie@mcchord.net",
        relationship="a trusted close colleague who works directly with Austin",
    ),
)

TRUSTED_CONTACTS: tuple[WorkflowContact, ...] = (SCHEDULING_ASSISTANT, *CLOSE_COLLEAGUES)


WORKFLOW_CONTEXT = f"""Known working relationships:
- {SCHEDULING_ASSISTANT.name} <{SCHEDULING_ASSISTANT.email}> is Austin's assistant and owns scheduling by default. Austin almost never coordinates availability or meeting logistics himself.
- {CLOSE_COLLEAGUES[0].name} <{CLOSE_COLLEAGUES[0].email}> works directly with Austin and is a trusted close colleague, never cold outreach.

Workflow rules:
- For scheduling, make Andrea the default action owner. Do not turn routine availability, calendar coordination, rescheduling, or logistics into an Austin action item.
- If Andrea is already on To or Cc, treat routine scheduling as already delegated: normally needs_reply=false, category=fyi, and low priority for Austin. Escalate only when the message explicitly asks Austin for a substantive decision or is genuinely urgent.
- If Andrea is not included and a scheduling reply is needed, the first/default quick reply should hand coordination to Andrea at {SCHEDULING_ASSISTANT.email}; do not volunteer Austin's availability as the default.
- Andrea or Angie appearing on Cc is meaningful relationship context, but Cc alone does not mean Austin owes a reply. Judge any separate request addressed directly to Austin on its merits.
"""


def normalize_address(value: Any) -> str:
    """Return a normalized mailbox address from Gmail JSON or header text."""
    if isinstance(value, Mapping):
        value = value.get("address") or value.get("email") or ""
    if not isinstance(value, str):
        return ""
    _name, parsed = parseaddr(value)
    return (parsed or value).strip().lower()


def address_is_present(values: Iterable[Any] | None, address: str) -> bool:
    target = address.strip().lower()
    return any(normalize_address(value) == target for value in (values or []))


def contact_is_recipient(email: Any, contact: WorkflowContact) -> bool:
    return address_is_present(getattr(email, "to_addresses", None), contact.email) or address_is_present(
        getattr(email, "cc_addresses", None), contact.email
    )


def contact_is_sender(email: Any, contact: WorkflowContact) -> bool:
    return normalize_address(getattr(email, "from_address", None)) == contact.email


def workflow_context_for_message(email: Any) -> str:
    """Add message-specific relationship signals to the stable context."""
    observations: list[str] = []
    if address_is_present(getattr(email, "cc_addresses", None), SCHEDULING_ASSISTANT.email):
        observations.append(
            "Andrea is CC'd on this message. Routine scheduling is already in her hands; "
            "do not put it in Austin's reply queue."
        )
    elif address_is_present(getattr(email, "to_addresses", None), SCHEDULING_ASSISTANT.email):
        observations.append(
            "Andrea is a direct recipient of this message. Routine scheduling is already "
            "delegated to her."
        )

    for contact in CLOSE_COLLEAGUES:
        if contact_is_sender(email, contact):
            observations.append(f"This message is from trusted colleague {contact.name}.")
        elif contact_is_recipient(email, contact):
            observations.append(f"Trusted colleague {contact.name} is included on this message.")

    if contact_is_sender(email, SCHEDULING_ASSISTANT):
        observations.append(
            "This message is directly from Andrea; prioritize any decision or information she "
            "explicitly asks Austin to provide."
        )

    if not observations:
        return WORKFLOW_CONTEXT
    return WORKFLOW_CONTEXT + "\nMessage-specific relationship signals:\n- " + "\n- ".join(observations) + "\n"


def _delegate_reply_body(andrea_in_thread: bool) -> str:
    if andrea_in_thread:
        return "Thanks—Andrea is copied here and will coordinate the scheduling details."
    return (
        "Thanks. My assistant, Andrea Durbin, handles my scheduling; please coordinate "
        f"with her directly at {SCHEDULING_ASSISTANT.email}."
    )


def _with_delegate_option(options: Any, *, andrea_in_thread: bool) -> list[dict]:
    existing = [option for option in (options or []) if isinstance(option, dict)]
    for index, option in enumerate(existing):
        option_text = f"{option.get('label', '')} {option.get('body', '')}".lower()
        if "andrea" in option_text or SCHEDULING_ASSISTANT.email in option_text:
            if index:
                existing.insert(0, existing.pop(index))
            return existing[:4]

    delegate = {
        "label": "Andrea to coordinate",
        "intent": "defer",
        "body": _delegate_reply_body(andrea_in_thread),
    }
    return [delegate, *existing][:4]


def apply_workflow_routing(email: Any, analysis_data: dict) -> dict:
    """Apply narrow, explainable safeguards to an LLM email analysis.

    The model still decides whether a message contains a substantive or urgent
    request. Routine low/normal-priority scheduling already sent to Andrea is
    removed from Austin's own queue; high and urgent messages remain visible.
    """
    routed = dict(analysis_data)

    sender_is_trusted = any(contact_is_sender(email, contact) for contact in TRUSTED_CONTACTS)
    if sender_is_trusted:
        was_marked_subscription = bool(routed.get("is_subscription"))
        routed["is_subscription"] = False
        if was_marked_subscription and routed.get("category") == "can_ignore":
            routed["category"] = "fyi"
            routed["priority"] = max(1, int(routed.get("priority", 1) or 0))

    if routed.get("conversation_type") != "scheduling":
        return routed

    andrea_in_thread = contact_is_recipient(email, SCHEDULING_ASSISTANT)
    andrea_is_sender = contact_is_sender(email, SCHEDULING_ASSISTANT)
    priority = int(routed.get("priority", 1) or 0)

    if andrea_in_thread and priority < 2:
        routed["priority"] = min(priority, 1)
        routed["needs_reply"] = False
        if routed.get("category") in {"awaiting_reply", "urgent"}:
            routed["category"] = "fyi"
        routed["suggested_reply"] = None
        routed["reply_options"] = None
        routed["action_items"] = []

        context = dict(routed.get("context") or {})
        context["requires_action"] = False
        context["workflow_routing"] = "Routine scheduling is delegated to Andrea, who is included on the message."
        routed["context"] = context
        return routed

    if routed.get("needs_reply") and not andrea_is_sender:
        options = _with_delegate_option(
            routed.get("reply_options"),
            andrea_in_thread=andrea_in_thread,
        )
        routed["reply_options"] = options
        routed["suggested_reply"] = options[0]["body"]

    return routed


def delegated_scheduling_sql(conversation_type_column: Any, to_column: Any, cc_column: Any):
    """SQL predicate for routine scheduling already routed to Andrea.

    Gmail stores recipients as JSON objects with an ``address`` field. Casting
    the small recipient arrays to text also covers legacy string arrays and
    provides case-insensitive matching. Keeping this predicate next to the
    Python relationship logic lets read-time queues correct older AI rows
    without a destructive data rewrite.
    """
    address = SCHEDULING_ASSISTANT.email
    address_pattern = f"%{address}%"
    return and_(
        conversation_type_column == "scheduling",
        or_(
            func.coalesce(cast(to_column, Text), "").ilike(address_pattern),
            func.coalesce(cast(cc_column, Text), "").ilike(address_pattern),
        ),
    )
