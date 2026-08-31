export const INBOX_RULE_PLACEMENTS = Object.freeze(['focused', 'other']);
export const INBOX_RULE_SCOPES = Object.freeze(['conversation', 'sender', 'domain']);

function requireInteger(value, label) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error(`${label} is invalid`);
  return parsed;
}

function requireUuid(value, label) {
  const text = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(text)) {
    throw new Error(`${label} is invalid`);
  }
  return text;
}

export function inboxPlacementLabel(placement) {
  if (placement === 'focused') return 'Focused';
  if (placement === 'other') return 'Other';
  return '';
}

export function inboxRuleScopeLabel(scope) {
  if (scope === 'conversation') return 'This conversation';
  if (scope === 'sender') return 'This sender';
  if (scope === 'domain') return 'This exact domain';
  return '';
}

export function inboxRuleFutureEffect(scope) {
  if (scope === 'conversation') return 'Future messages in this conversation will use this section.';
  if (scope === 'sender') return 'Future Inbox conversations from this sender will use this section.';
  if (scope === 'domain') return 'Future Inbox conversations from this exact domain will use this section.';
  return '';
}

export function normalizeInboxRule(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('Inbox rule is missing');
  const scope = String(raw.scope || '');
  const placement = String(raw.placement || '');
  if (!INBOX_RULE_SCOPES.includes(scope)) throw new Error('Inbox rule scope is invalid');
  if (!INBOX_RULE_PLACEMENTS.includes(placement)) throw new Error('Inbox rule placement is invalid');
  const accountEmail = String(raw.account_email || '').trim();
  const displayValue = String(raw.display_value || '').trim();
  if (!accountEmail || !displayValue) throw new Error('Inbox rule display details are missing');
  return {
    id: requireUuid(raw.id, 'Inbox rule'),
    account_id: requireInteger(raw.account_id, 'Inbox rule account'),
    account_email: accountEmail,
    scope,
    display_value: displayValue,
    placement,
    enabled: raw.enabled !== false,
    revision: requireInteger(raw.revision, 'Inbox rule revision'),
    created_at: raw.created_at || null,
    updated_at: raw.updated_at || null,
  };
}

export function normalizeInboxRuleCandidate(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('Rule candidate is missing');
  const accountEmail = String(raw.account_email || '').trim();
  const conversationLabel = String(raw.conversation_label || '').trim();
  const senderAddress = String(raw.sender_address || '').trim();
  const senderDomain = String(raw.sender_domain || '').trim();
  if (!accountEmail || !conversationLabel) {
    throw new Error('Rule candidate display details are missing');
  }
  const rules = (raw.rules || []).map(normalizeInboxRule);
  const values = {
    conversation: conversationLabel,
    sender: senderAddress,
    domain: senderDomain,
  };
  const scopes = INBOX_RULE_SCOPES
    .filter(scope => Boolean(values[scope]))
    .map(scope => ({
      scope,
      display_label: `${inboxRuleScopeLabel(scope)} · ${values[scope]}`,
      current_rule: rules.find(rule => rule.scope === scope) || null,
    }));
  return {
    candidate: {
      anchor_email_id: requireInteger(raw.anchor_email_id, 'Conversation'),
      account_id: requireInteger(raw.account_id, 'Account'),
      account_email: accountEmail,
    },
    scopes,
  };
}

export function normalizeInboxRulesResponse(raw) {
  const items = (raw?.items || []).map(normalizeInboxRule);
  const maximum = Number(raw?.max_rules_per_account);
  return {
    items,
    max_rules_per_account: Number.isInteger(maximum) && maximum > 0 ? maximum : null,
  };
}

export function newInboxRuleCreateId() {
  if (typeof globalThis.crypto?.randomUUID !== 'function') {
    throw new Error('A secure rule request ID is unavailable');
  }
  return globalThis.crypto.randomUUID();
}

export function createInboxRulePayload({
  createId,
  accountId,
  anchorEmailId,
  scope,
  placement,
  currentRule = null,
}) {
  if (!INBOX_RULE_SCOPES.includes(scope)) throw new Error('Choose what this rule should match');
  if (!INBOX_RULE_PLACEMENTS.includes(placement)) throw new Error('Choose Focused or Other');
  return {
    create_id: requireUuid(createId, 'Rule request'),
    account_id: requireInteger(accountId, 'Account'),
    anchor_email_id: requireInteger(anchorEmailId, 'Conversation'),
    scope,
    placement,
    enabled: true,
    expected_revision: currentRule ? requireInteger(currentRule.revision, 'Expected revision') : 0,
  };
}

export function updateInboxRulePayload({ placement, enabled, revision }) {
  if (!INBOX_RULE_PLACEMENTS.includes(placement)) throw new Error('Choose Focused or Other');
  return {
    placement,
    enabled: Boolean(enabled),
    revision: requireInteger(revision, 'Inbox rule revision'),
  };
}

export function normalizeInboxRuleMutation(raw, previousRule = null) {
  const rule = normalizeInboxRule(raw);
  const previous = previousRule ? normalizeInboxRule(previousRule) : null;
  return {
    rule,
    previous_rule: previous,
    changed: !previous
      || previous.placement !== rule.placement
      || previous.enabled !== rule.enabled
      || previous.revision !== rule.revision,
  };
}

export function inboxRuleUndoOperation(mutation) {
  const normalized = mutation?.rule
    ? {
        rule: normalizeInboxRule(mutation.rule),
        previous_rule: mutation.previous_rule ? normalizeInboxRule(mutation.previous_rule) : null,
        changed: mutation.changed !== false,
      }
    : normalizeInboxRuleMutation(mutation);
  if (!normalized.changed) return null;
  if (!normalized.previous_rule) {
    return {
      type: 'delete',
      ruleId: normalized.rule.id,
      revision: normalized.rule.revision,
    };
  }
  return {
    type: 'restore',
    ruleId: normalized.rule.id,
    payload: updateInboxRulePayload({
      placement: normalized.previous_rule.placement,
      enabled: normalized.previous_rule.enabled,
      revision: normalized.rule.revision,
    }),
  };
}

export function isInboxRuleConflict(error) {
  return Number(error?.status) === 409;
}
