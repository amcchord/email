"""Strict canonical mailbox identities used by local deterministic rules."""

import re
from email.utils import getaddresses

import idna


MAX_MAILBOX_LENGTH = 320
MAX_DOMAIN_LENGTH = 253
_LOCAL_PART = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}$")


class MailboxIdentityError(ValueError):
    pass


def normalize_domain(value: str) -> str:
    if not isinstance(value, str):
        raise MailboxIdentityError("Email domain is invalid")
    candidate = value.strip().rstrip(".")
    if not candidate or len(candidate) > MAX_DOMAIN_LENGTH:
        raise MailboxIdentityError("Email domain is invalid")
    if any(character.isspace() for character in candidate) or candidate.startswith("["):
        raise MailboxIdentityError("Email domain is invalid")
    try:
        normalized = idna.encode(
            candidate,
            uts46=True,
            std3_rules=True,
        ).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError) as error:
        raise MailboxIdentityError("Email domain is invalid") from error
    if len(normalized) > MAX_DOMAIN_LENGTH:
        raise MailboxIdentityError("Email domain is invalid")
    return normalized


def normalize_mailbox(value: str) -> str:
    if not isinstance(value, str):
        raise MailboxIdentityError("Sender address is invalid")
    raw = value.strip()
    if not raw or len(raw) > 512 or "\r" in raw or "\n" in raw:
        raise MailboxIdentityError("Sender address is invalid")
    parsed = getaddresses([raw])
    if len(parsed) != 1:
        raise MailboxIdentityError("Sender address is invalid")
    _display_name, address = parsed[0]
    if address.count("@") != 1:
        raise MailboxIdentityError("Sender address is invalid")
    local_part, domain = address.rsplit("@", 1)
    if not _LOCAL_PART.fullmatch(local_part):
        raise MailboxIdentityError("Sender address is invalid")
    normalized = f"{local_part.lower()}@{normalize_domain(domain)}"
    if len(normalized) > MAX_MAILBOX_LENGTH:
        raise MailboxIdentityError("Sender address is invalid")
    return normalized


def normalize_stored_mailbox(value: str) -> str:
    """Normalize a parsed stored mailbox only when SQL can match it exactly.

    PostgreSQL can case-fold ASCII and remove a terminal domain dot, but it
    cannot perform UTS46/IDNA conversion. Strictly validate every address and
    fail closed when IDNA would transform the synchronized representation.
    """
    normalized = normalize_mailbox(value)
    raw = value.strip()
    parsed = getaddresses([raw])
    address = parsed[0][1]
    local_part, domain = address.rsplit("@", 1)
    sql_compatible = f"{local_part.lower()}@{domain.rstrip('.').lower()}"
    if normalized != sql_compatible:
        raise MailboxIdentityError(
            "Sender address cannot be matched safely by local rules"
        )
    return normalized


def mailbox_domain(value: str) -> str:
    return normalize_mailbox(value).rsplit("@", 1)[1]
