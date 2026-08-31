export const FOLLOW_UP_DELAY_DAYS = Object.freeze([1, 2, 3, 5, 7, 14]);
export const FOLLOW_UP_REMINDER_MODES = Object.freeze(['default', 'enabled', 'disabled']);

const DEFAULT_DELAY_DAYS = 3;
const DEFAULT_WAKE_LOCAL_TIME = '09:00';
const DEFAULT_WEEKDAYS_ONLY = true;
const WAKE_TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$/;

function validDelayDays(value) {
  const days = Number(value);
  return Number.isSafeInteger(days) && days >= 1 && days <= 30;
}

export function followUpDelayChoices(currentValue = null) {
  const current = Number(currentValue);
  if (!validDelayDays(current) || FOLLOW_UP_DELAY_DAYS.includes(current)) {
    return [...FOLLOW_UP_DELAY_DAYS];
  }
  return [...FOLLOW_UP_DELAY_DAYS, current].sort((left, right) => left - right);
}

export function validFollowUpTimeZone(value) {
  const timeZone = String(value ?? '').trim();
  if (!timeZone) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone }).format();
    return true;
  } catch {
    return false;
  }
}

export function browserFollowUpTimeZone() {
  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return validFollowUpTimeZone(timeZone) ? timeZone : 'UTC';
  } catch {
    return 'UTC';
  }
}

function normalizeWakeLocalTime(value) {
  const match = WAKE_TIME_RE.exec(String(value ?? '').trim());
  return match ? `${match[1]}:${match[2]}` : null;
}

function normalizedDefaultTimeZone(browserTimeZone, serverTimeZone) {
  if (validFollowUpTimeZone(browserTimeZone)) return String(browserTimeZone).trim();
  if (validFollowUpTimeZone(serverTimeZone)) return String(serverTimeZone).trim();
  return 'UTC';
}

export function normalizeFollowUpPolicy(record, {
  browserTimeZone = browserFollowUpTimeZone(),
} = {}) {
  if (!record || typeof record !== 'object' || Array.isArray(record)) return null;

  const accountId = Number(record.account_id);
  const accountEmail = String(record.account_email ?? '').trim();
  const revision = Number(record.revision ?? 0);
  if (
    !Number.isSafeInteger(accountId)
    || accountId <= 0
    || !accountEmail
    || !Number.isSafeInteger(revision)
    || revision < 0
  ) return null;

  const isUnsavedDefault = revision === 0;
  const enabled = typeof record.enabled === 'boolean'
    ? record.enabled
    : (isUnsavedDefault ? false : null);
  const delayCandidate = record.delay_days == null && isUnsavedDefault
    ? DEFAULT_DELAY_DAYS
    : Number(record.delay_days);
  const wakeLocalTime = record.wake_local_time == null && isUnsavedDefault
    ? DEFAULT_WAKE_LOCAL_TIME
    : normalizeWakeLocalTime(record.wake_local_time);
  const weekdaysOnly = typeof record.weekdays_only === 'boolean'
    ? record.weekdays_only
    : (isUnsavedDefault ? DEFAULT_WEEKDAYS_ONLY : null);
  const timeZone = isUnsavedDefault
    ? normalizedDefaultTimeZone(browserTimeZone, record.time_zone)
    : (validFollowUpTimeZone(record.time_zone) ? String(record.time_zone).trim() : null);

  if (
    enabled === null
    || !validDelayDays(delayCandidate)
    || !wakeLocalTime
    || weekdaysOnly === null
    || !timeZone
  ) return null;

  return {
    ...record,
    account_id: accountId,
    account_email: accountEmail,
    enabled,
    delay_days: delayCandidate,
    wake_local_time: wakeLocalTime,
    time_zone: timeZone,
    weekdays_only: weekdaysOnly,
    revision,
  };
}

export function normalizeFollowUpPolicyList(response, options = {}) {
  if (!response || typeof response !== 'object' || !Array.isArray(response.accounts)) {
    throw new Error('Automatic follow-up preferences response is invalid');
  }
  const accounts = response.accounts.map(record => normalizeFollowUpPolicy(record, options));
  if (accounts.some(account => account === null)) {
    throw new Error('Automatic follow-up preferences response is invalid');
  }
  const accountIds = new Set(accounts.map(account => account.account_id));
  if (accountIds.size !== accounts.length) {
    throw new Error('Automatic follow-up preferences response contains duplicate accounts');
  }
  const total = Number(response.total);
  if (!Number.isSafeInteger(total) || total < 0 || total !== accounts.length) {
    throw new Error('Automatic follow-up preferences response total is invalid');
  }
  return { accounts, total };
}

export function validateFollowUpPolicy(policy) {
  if (typeof policy?.enabled !== 'boolean') return 'Choose whether automatic follow-up reminders are on.';
  if (!validDelayDays(policy?.delay_days)) return 'Choose a wait period from 1 to 30 days.';
  if (!normalizeWakeLocalTime(policy?.wake_local_time)) return 'Choose a valid local reminder time.';
  if (!validFollowUpTimeZone(policy?.time_zone)) return 'The reminder time zone is invalid. Reload and try again.';
  if (typeof policy?.weekdays_only !== 'boolean') return 'Choose whether reminders should wait for weekdays.';
  const revision = Number(policy?.revision);
  if (!Number.isSafeInteger(revision) || revision < 0) return 'The preference revision is invalid. Reload and try again.';
  return '';
}

export function followUpPolicyPayload(policy) {
  const validationError = validateFollowUpPolicy(policy);
  if (validationError) throw new Error(validationError);
  return {
    enabled: policy.enabled,
    delay_days: Number(policy.delay_days),
    wake_local_time: normalizeWakeLocalTime(policy.wake_local_time),
    time_zone: String(policy.time_zone).trim(),
    weekdays_only: policy.weekdays_only,
    expected_revision: Number(policy.revision),
  };
}

function editableFields(policy) {
  const payload = followUpPolicyPayload(policy);
  delete payload.expected_revision;
  return payload;
}

export function followUpPolicyIsDirty(savedPolicy, draftPolicy) {
  try {
    return JSON.stringify(editableFields(savedPolicy)) !== JSON.stringify(editableFields(draftPolicy));
  } catch {
    return true;
  }
}

export function followUpPolicySummary(policy) {
  if (!policy?.enabled) return 'Off — no automatic reminders';
  const days = Number(policy.delay_days);
  const dayLabel = `${days} ${days === 1 ? 'day' : 'days'}`;
  const schedule = policy.weekdays_only ? 'weekdays only' : 'any day';
  const timeZone = validFollowUpTimeZone(policy.time_zone) ? ` · ${policy.time_zone}` : '';
  return `After ${dayLabel} at ${normalizeWakeLocalTime(policy.wake_local_time) || 'the chosen time'} · ${schedule}${timeZone}`;
}

export function normalizeFollowUpReminderMode(value) {
  const mode = String(value ?? '').trim().toLowerCase();
  return FOLLOW_UP_REMINDER_MODES.includes(mode) ? mode : 'default';
}

export function followUpPolicyForAccount(policies, accountId) {
  const id = Number(accountId);
  if (!Number.isSafeInteger(id) || id <= 0) return null;
  const records = Array.isArray(policies) ? policies : policies?.accounts;
  if (!Array.isArray(records)) return null;
  return records.find(policy => Number(policy?.account_id) === id) || null;
}

export function followUpReminderIsEnabled(mode, policy) {
  const normalized = normalizeFollowUpReminderMode(mode);
  if (normalized === 'enabled') return true;
  if (normalized === 'disabled') return false;
  return Boolean(policy?.enabled);
}

export function followUpSendSummary(policy) {
  if (!policy) return 'After 3 weekdays at 09:00 local time';
  const days = validDelayDays(policy.delay_days) ? Number(policy.delay_days) : DEFAULT_DELAY_DAYS;
  const dayLabel = `${days} ${days === 1 ? 'day' : 'days'}`;
  const schedule = policy.weekdays_only === false ? 'any day' : 'weekdays only';
  const localTime = normalizeWakeLocalTime(policy.wake_local_time) || DEFAULT_WAKE_LOCAL_TIME;
  const timeZone = validFollowUpTimeZone(policy.time_zone) ? ` · ${policy.time_zone}` : '';
  return `After ${dayLabel} at ${localTime} · ${schedule}${timeZone}`;
}

export function followUpRequestFields({
  mode = 'default',
  policy = null,
  timeZone = browserFollowUpTimeZone(),
} = {}) {
  const policyTimeZone = validFollowUpTimeZone(policy?.time_zone)
    ? String(policy.time_zone).trim()
    : null;
  const fallbackTimeZone = validFollowUpTimeZone(timeZone) ? String(timeZone).trim() : 'UTC';
  return {
    follow_up_reminder: normalizeFollowUpReminderMode(mode),
    follow_up_time_zone: policyTimeZone || fallbackTimeZone,
  };
}
