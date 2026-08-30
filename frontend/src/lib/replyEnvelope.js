export const REPLY_ENVELOPE_UNAVAILABLE = Object.freeze({
  INVALID_INPUT: 'invalid_input',
  INVALID_MODE: 'invalid_mode',
  MESSAGE_DIRECTION_MISSING: 'message_direction_missing',
  SOURCE_MESSAGE_ID_INVALID: 'source_message_id_invalid',
  OWNED_IDENTITY_INVALID: 'owned_identity_invalid',
  SOURCE_ACCOUNT_IDENTITY_MISSING: 'source_account_identity_missing',
  SOURCE_ACCOUNT_IDENTITY_INVALID: 'source_account_identity_invalid',
  SOURCE_ACCOUNT_NOT_FOUND: 'source_account_not_found',
  SOURCE_ACCOUNT_MISMATCH: 'source_account_mismatch',
  SOURCE_ACCOUNT_AMBIGUOUS: 'source_account_ambiguous',
  SOURCE_ACCOUNT_INACTIVE: 'source_account_inactive',
  REPLY_TARGET_INVALID: 'reply_target_invalid',
  REPLY_TARGET_IS_OWNED: 'reply_target_is_owned',
  RECIPIENT_LIST_INVALID: 'recipient_list_invalid',
  REPLY_TARGET_MISSING: 'reply_target_missing',
  THREAD_DETAILS_UNAVAILABLE: 'thread_details_unavailable',
});

export const REPLY_ENVELOPE_MODES = Object.freeze({
  REPLY: 'reply',
  REPLY_ALL: 'reply-all',
});

export function replyCompletionStillCurrent({
  capturedGeneration,
  currentGeneration,
  capturedEmailId,
  currentEmailId,
  capturedBody,
  currentBody,
} = {}) {
  return capturedGeneration === currentGeneration
    && capturedEmailId != null
    && capturedEmailId === currentEmailId
    && capturedBody === currentBody;
}

function unavailable(reason) {
  return {
    available: false,
    reason,
    sourceAccount: null,
    envelope: null,
  };
}

function success(sourceAccount, envelope) {
  return {
    available: true,
    reason: null,
    sourceAccount,
    envelope,
  };
}

function hasIdentity(value) {
  return value !== null && value !== undefined && String(value).trim() !== '';
}

/**
 * Return a canonical mailbox address for comparison and sending.
 *
 * API address values can be strings, display-address strings, or objects from
 * EmailAddress. Canonical output deliberately omits display names: the same
 * value is shown in the reply envelope and sent to the compose endpoint.
 */
export function normalizeReplyAddress(value) {
  let candidate = value;
  if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
    candidate = candidate.address ?? candidate.email ?? '';
  }
  if (typeof candidate !== 'string') return null;

  candidate = candidate.trim();
  const angleAddress = /^(?:"[^"]*"|[^<>]*)<\s*([^<>]+?)\s*>$/u.exec(candidate);
  if (angleAddress) candidate = angleAddress[1];
  else if (/[<>]/u.test(candidate)) return null;
  candidate = candidate.trim().replace(/^mailto:/iu, '').trim().toLowerCase();

  // This is intentionally structural rather than a restrictive RFC mailbox
  // validator. It rejects ambiguous/header-shaped input without excluding
  // valid international or uncommon local parts.
  const atIndex = candidate.indexOf('@');
  if (
    !candidate
    || atIndex <= 0
    || atIndex !== candidate.lastIndexOf('@')
    || atIndex === candidate.length - 1
    || /[\s<>;,]/u.test(candidate)
  ) {
    return null;
  }
  return candidate;
}

function normalizeAccountId(value) {
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

function accountIdentityCandidates(account) {
  const candidates = [account?.email, account?.account_email];
  for (const key of ['aliases', 'identities', 'owned_addresses', 'send_as']) {
    if (Array.isArray(account?.[key])) candidates.push(...account[key]);
  }
  return candidates;
}

function normalizeAccounts(accounts) {
  if (!Array.isArray(accounts) || accounts.length === 0) {
    return { ok: false, reason: REPLY_ENVELOPE_UNAVAILABLE.OWNED_IDENTITY_INVALID };
  }

  const normalized = [];
  const owned = new Set();
  for (const account of accounts) {
    const id = normalizeAccountId(account?.id);
    const email = normalizeReplyAddress(account?.email);
    if (!id || !email) {
      return { ok: false, reason: REPLY_ENVELOPE_UNAVAILABLE.OWNED_IDENTITY_INVALID };
    }

    const identities = new Set();
    for (const candidate of accountIdentityCandidates(account)) {
      if (!hasIdentity(candidate)) continue;
      const address = normalizeReplyAddress(candidate);
      if (!address) {
        return { ok: false, reason: REPLY_ENVELOPE_UNAVAILABLE.OWNED_IDENTITY_INVALID };
      }
      identities.add(address);
      owned.add(address);
    }
    identities.add(email);
    owned.add(email);
    normalized.push({ raw: account, id, email, identities });
  }

  return { ok: true, accounts: normalized, owned };
}

/**
 * Resolve only the account explicitly carried by the source message.
 *
 * A single configured account is not a safe fallback. When both account_id and
 * account_email are present they must independently resolve to the same active
 * account.
 */
export function resolveReplySourceAccount({ message, accounts } = {}) {
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.INVALID_INPUT);
  }

  const accountState = normalizeAccounts(accounts);
  if (!accountState.ok) return unavailable(accountState.reason);

  const hasAccountId = hasIdentity(message.account_id);
  const hasAccountEmail = hasIdentity(message.account_email);
  if (!hasAccountId && !hasAccountEmail) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_IDENTITY_MISSING);
  }

  const accountId = hasAccountId ? normalizeAccountId(message.account_id) : null;
  const accountEmail = hasAccountEmail ? normalizeReplyAddress(message.account_email) : null;
  if ((hasAccountId && !accountId) || (hasAccountEmail && !accountEmail)) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_IDENTITY_INVALID);
  }

  const byId = accountId
    ? accountState.accounts.filter(account => account.id === accountId)
    : [];
  const byEmail = accountEmail
    ? accountState.accounts.filter(account => account.email === accountEmail)
    : [];

  if (byId.length > 1 || byEmail.length > 1) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_AMBIGUOUS);
  }

  let selected = null;
  if (accountId && accountEmail) {
    if (byId.length === 0 && byEmail.length === 0) {
      return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_NOT_FOUND);
    }
    if (byId.length !== 1 || byEmail.length !== 1 || byId[0] !== byEmail[0]) {
      return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_MISMATCH);
    }
    selected = byId[0];
  } else {
    const matches = accountId ? byId : byEmail;
    if (matches.length !== 1) {
      return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_NOT_FOUND);
    }
    selected = matches[0];
  }

  if (selected.raw.is_active !== true) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_INACTIVE);
  }

  return {
    available: true,
    reason: null,
    sourceAccount: { id: selected.id, email: selected.email },
    envelope: null,
    ownedIdentities: accountState.owned,
  };
}

function normalizeRecipientList(value) {
  if (value === null || value === undefined) return { ok: true, recipients: [] };
  if (!Array.isArray(value)) return { ok: false, recipients: [] };

  const recipients = [];
  for (const item of value) {
    const address = normalizeReplyAddress(item);
    if (!address) return { ok: false, recipients: [] };
    recipients.push(address);
  }
  return { ok: true, recipients };
}

function uniqueExternalRecipients(recipients, owned, alreadyUsed = new Set()) {
  const result = [];
  const used = new Set(alreadyUsed);
  for (const address of recipients) {
    if (owned.has(address) || used.has(address)) continue;
    used.add(address);
    result.push(address);
  }
  return result;
}

function replySubject(subject) {
  const normalized = typeof subject === 'string' ? subject.trim() : '';
  return /^re\s*:/iu.test(normalized) ? normalized : `Re: ${normalized}`;
}

function replyMetadata(message) {
  const messageId = typeof message.message_id_header === 'string'
    ? message.message_id_header.trim() || null
    : null;
  const existingReferences = typeof message.references_header === 'string'
    ? message.references_header.trim()
    : (typeof message.references === 'string' ? message.references.trim() : '');
  const referenceParts = existingReferences ? existingReferences.split(/\s+/u) : [];
  if (messageId && !referenceParts.includes(messageId)) referenceParts.push(messageId);
  const references = referenceParts.join(' ') || null;
  const threadId = message.gmail_thread_id ?? message.thread_id ?? null;
  return {
    subject: replySubject(message.subject),
    in_reply_to: messageId,
    references,
    thread_id: threadId,
  };
}

/**
 * Build a recipient envelope for Reply or Reply All.
 *
 * Success returns an `envelope` containing only compose/send payload fields.
 * Failure returns a stable reason and no partial envelope, so callers cannot
 * accidentally send with guessed account or recipient data.
 */
export function buildReplyEnvelope({ message, accounts, mode = REPLY_ENVELOPE_MODES.REPLY } = {}) {
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.INVALID_INPUT);
  }
  if (mode !== REPLY_ENVELOPE_MODES.REPLY && mode !== REPLY_ENVELOPE_MODES.REPLY_ALL) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.INVALID_MODE);
  }
  if (typeof message.is_sent !== 'boolean') {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.MESSAGE_DIRECTION_MISSING);
  }
  const sourceEmailId = Number(message.id);
  if (!Number.isSafeInteger(sourceEmailId) || sourceEmailId <= 0) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.SOURCE_MESSAGE_ID_INVALID);
  }

  const resolution = resolveReplySourceAccount({ message, accounts });
  if (!resolution.available) return resolution;
  const { sourceAccount, ownedIdentities } = resolution;

  let to = [];
  let cc = [];

  if (message.is_sent) {
    const toState = normalizeRecipientList(message.to_addresses);
    if (!toState.ok) return unavailable(REPLY_ENVELOPE_UNAVAILABLE.RECIPIENT_LIST_INVALID);

    const externalTo = uniqueExternalRecipients(toState.recipients, ownedIdentities);
    if (mode === REPLY_ENVELOPE_MODES.REPLY) {
      to = externalTo.slice(0, 1);
    } else {
      const ccState = normalizeRecipientList(message.cc_addresses);
      if (!ccState.ok) return unavailable(REPLY_ENVELOPE_UNAVAILABLE.RECIPIENT_LIST_INVALID);
      to = externalTo;
      cc = uniqueExternalRecipients(ccState.recipients, ownedIdentities, new Set(to));
      // Keep the payload convention that the primary visible recipient is To,
      // even for unusual sent messages that originally addressed only Cc.
      if (to.length === 0 && cc.length > 0) to = [cc.shift()];
    }
  } else {
    const hasReplyTo = hasIdentity(message.reply_to);
    const primary = normalizeReplyAddress(hasReplyTo ? message.reply_to : message.from_address);
    if (!primary) return unavailable(REPLY_ENVELOPE_UNAVAILABLE.REPLY_TARGET_INVALID);
    if (ownedIdentities.has(primary)) {
      return unavailable(REPLY_ENVELOPE_UNAVAILABLE.REPLY_TARGET_IS_OWNED);
    }

    to = [primary];
    if (mode === REPLY_ENVELOPE_MODES.REPLY_ALL) {
      const toState = normalizeRecipientList(message.to_addresses);
      const ccState = normalizeRecipientList(message.cc_addresses);
      if (!toState.ok || !ccState.ok) {
        return unavailable(REPLY_ENVELOPE_UNAVAILABLE.RECIPIENT_LIST_INVALID);
      }
      to = uniqueExternalRecipients(
        [primary, ...toState.recipients],
        ownedIdentities,
      );
      cc = uniqueExternalRecipients(ccState.recipients, ownedIdentities, new Set(to));
    }
  }

  if (to.length === 0 && cc.length === 0) {
    return unavailable(REPLY_ENVELOPE_UNAVAILABLE.REPLY_TARGET_MISSING);
  }

  return success(sourceAccount, {
    account_id: sourceAccount.id,
    source_email_id: sourceEmailId,
    to,
    cc,
    bcc: [],
    ...replyMetadata(message),
  });
}
