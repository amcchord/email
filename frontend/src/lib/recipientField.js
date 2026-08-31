const CONTROL_RE = /[\u0000-\u001f\u007f]/u;
const MAILBOX_SPECIAL_RE = /[",;<>@]/u;

function cleanDisplayName(value) {
  return String(value ?? '').trim().replace(/\s+/gu, ' ');
}

function decodeDisplayName(value) {
  const candidate = String(value ?? '').trim();
  if (!candidate) return '';
  if (!candidate.startsWith('"')) {
    return candidate.includes('"') ? null : cleanDisplayName(candidate);
  }
  if (!candidate.endsWith('"') || candidate.length < 2) return null;
  let decoded = '';
  let escaped = false;
  for (const character of candidate.slice(1, -1)) {
    if (escaped) {
      decoded += character;
      escaped = false;
    } else if (character === '\\') {
      escaped = true;
    } else if (character === '"') {
      return null;
    } else {
      decoded += character;
    }
  }
  if (escaped) return null;
  return cleanDisplayName(decoded);
}

function normalizeAddress(value) {
  const candidate = String(value ?? '').trim();
  if (
    !candidate
    || candidate.length > 254
    || CONTROL_RE.test(candidate)
    || /[\s<>()\[\],;:"\\]/u.test(candidate)
  ) return null;

  const parts = candidate.split('@');
  if (parts.length !== 2) return null;
  const [local, rawDomain] = parts;
  const domain = rawDomain.toLocaleLowerCase();
  if (
    !local
    || local.length > 64
    || !/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$/u.test(local)
    || local.startsWith('.')
    || local.endsWith('.')
    || local.includes('..')
    || !domain
    || domain.length > 253
    || domain.startsWith('.')
    || domain.endsWith('.')
    || domain.includes('..')
  ) return null;
  const labels = domain.split('.');
  if (labels.length < 2 || labels.some(label => (
    !label
    || label.length > 63
    || label.startsWith('-')
    || label.endsWith('-')
    || !/^[\p{L}\p{N}-]+$/u.test(label)
  ))) return null;
  return `${local}@${domain}`;
}

/** Split a pasted mailbox list without treating quoted display-name commas as separators. */
export function splitMailboxList(value) {
  const source = String(value ?? '');
  const parts = [];
  let current = '';
  let quoted = false;
  let escaped = false;
  let angleDepth = 0;

  const flush = () => {
    const candidate = current.trim();
    if (candidate) parts.push(candidate);
    current = '';
  };

  for (const character of source) {
    if (escaped) {
      current += character;
      escaped = false;
      continue;
    }
    if (quoted && character === '\\') {
      current += character;
      escaped = true;
      continue;
    }
    if (character === '"') {
      quoted = !quoted;
      current += character;
      continue;
    }
    if (!quoted && character === '<') angleDepth += 1;
    if (!quoted && character === '>') angleDepth = Math.max(0, angleDepth - 1);
    if (!quoted && angleDepth === 0 && (character === ',' || character === ';' || character === '\n' || character === '\r')) {
      flush();
      continue;
    }
    current += character;
  }
  flush();
  return parts;
}

export function formatMailbox({ address, name = '' } = {}) {
  const normalizedAddress = normalizeAddress(address);
  if (!normalizedAddress) return null;
  const normalizedName = cleanDisplayName(name);
  if (!normalizedName) return normalizedAddress;
  if (CONTROL_RE.test(normalizedName)) return null;
  const display = MAILBOX_SPECIAL_RE.test(normalizedName)
    ? `"${normalizedName.replace(/(["\\])/gu, '\\$1')}"`
    : normalizedName;
  return `${display} <${normalizedAddress}>`;
}

export function parseMailbox(value) {
  const candidate = String(value ?? '').trim();
  if (!candidate || CONTROL_RE.test(candidate)) return null;

  let name = '';
  let addressSource = candidate;
  const angleStart = candidate.lastIndexOf('<');
  if (angleStart >= 0) {
    if (!candidate.endsWith('>') || candidate.indexOf('<') !== angleStart) return null;
    name = decodeDisplayName(candidate.slice(0, angleStart));
    if (name === null) return null;
    addressSource = candidate.slice(angleStart + 1, -1).trim();
  } else if (candidate.includes('>')) {
    return null;
  }

  const address = normalizeAddress(addressSource);
  if (!address) return null;
  const mailbox = formatMailbox({ address, name });
  if (!mailbox) return null;
  return {
    address,
    name,
    mailbox,
    identity: address.toLocaleLowerCase(),
  };
}

export function normalizeMailbox(value) {
  return parseMailbox(value)?.mailbox ?? null;
}

export function mailboxIdentity(value) {
  return parseMailbox(value)?.identity ?? null;
}

export function parseMailboxList(value) {
  const mailboxes = [];
  const invalid = [];
  for (const candidate of splitMailboxList(value)) {
    const parsed = parseMailbox(candidate);
    if (parsed) mailboxes.push(parsed.mailbox);
    else invalid.push(candidate);
  }
  return { mailboxes, invalid };
}

export function recipientCollectionIdentities(collections = []) {
  const identities = new Set();
  for (const collection of collections || []) {
    for (const mailbox of Array.isArray(collection) ? collection : []) {
      const identity = mailboxIdentity(mailbox);
      if (identity) identities.add(identity);
    }
  }
  return identities;
}

/**
 * Merge manually entered/pasted mailboxes into one field while reporting
 * invalid and duplicate values without discarding the caller's committed list.
 */
export function commitRecipientInput(input, {
  recipients = [],
  recipientCollections = [],
  isDuplicate = null,
  field = 'recipients',
} = {}) {
  const parsed = parseMailboxList(input);
  const next = [...(Array.isArray(recipients) ? recipients : [])];
  const existing = recipientCollectionIdentities([next, ...(recipientCollections || [])]);
  const added = [];
  const duplicates = [];

  for (const mailbox of parsed.mailboxes) {
    const identity = mailboxIdentity(mailbox);
    const duplicate = existing.has(identity) || Boolean(isDuplicate?.({
      mailbox,
      identity,
      recipients: next,
      recipientCollections,
      field,
    }));
    if (duplicate) {
      duplicates.push(mailbox);
      continue;
    }
    existing.add(identity);
    next.push(mailbox);
    added.push(mailbox);
  }

  return {
    recipients: next,
    added,
    duplicates,
    invalid: parsed.invalid,
  };
}

export function normalizeRecipientSuggestion(candidate) {
  const record = candidate && typeof candidate === 'object' && !Array.isArray(candidate)
    ? candidate
    : {};
  const address = record.email ?? record.address ?? '';
  const name = record.name ?? record.display_name ?? '';
  const source = typeof candidate === 'string'
    ? candidate
    : record.mailbox ?? record.value ?? formatMailbox({ address, name });
  const parsed = parseMailbox(source);
  if (!parsed) return null;
  return {
    ...record,
    ...parsed,
    label: cleanDisplayName(record.label) || parsed.name || parsed.address,
    detail: cleanDisplayName(record.detail) || (parsed.name ? parsed.address : ''),
  };
}

export function normalizeRecipientSuggestions(response, {
  recipients = [],
  recipientCollections = [],
} = {}) {
  const source = Array.isArray(response) ? response : response?.suggestions;
  if (!Array.isArray(source)) return [];
  const excluded = recipientCollectionIdentities([recipients, ...(recipientCollections || [])]);
  const seen = new Set();
  return source.map(normalizeRecipientSuggestion).filter(suggestion => {
    if (!suggestion || excluded.has(suggestion.identity) || seen.has(suggestion.identity)) return false;
    seen.add(suggestion.identity);
    return true;
  });
}

export function pendingMailboxHasOpenSyntax(value) {
  let quoted = false;
  let escaped = false;
  let angleDepth = 0;
  for (const character of String(value ?? '')) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quoted && character === '\\') {
      escaped = true;
      continue;
    }
    if (character === '"') quoted = !quoted;
    else if (!quoted && character === '<') angleDepth += 1;
    else if (!quoted && character === '>') angleDepth = Math.max(0, angleDepth - 1);
  }
  return quoted || angleDepth > 0 || escaped;
}
