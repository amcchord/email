const DAY_MS = 24 * 60 * 60 * 1000;

export const AVAILABILITY_DURATIONS = Object.freeze([15, 30, 45, 60]);
export const AVAILABILITY_RANGES = Object.freeze([7, 14]);
export const MAX_AVAILABILITY_SLOTS = 8;

export const AVAILABILITY_COVERAGE_STATES = Object.freeze([
  'ready',
  'calendar_not_enabled',
  'reauthorization_required',
  'sync_incomplete',
  'stale',
  'sync_error',
  'syncing',
]);

function positiveInteger(value) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function validIsoInstant(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

export function validAvailabilityTimeZone(value) {
  const timeZone = String(value || '').trim();
  if (!timeZone || timeZone.length > 64) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone }).format(new Date(0));
    return true;
  } catch {
    return false;
  }
}

export function browserAvailabilityTimeZone() {
  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return validAvailabilityTimeZone(timeZone) ? timeZone : 'UTC';
  } catch {
    return 'UTC';
  }
}

export function calendarScopedAvailabilityAccounts(accounts = []) {
  return (Array.isArray(accounts) ? accounts : []).filter(account => (
    positiveInteger(account?.id) !== null
    && account?.is_active !== false
    && account?.has_calendar_scope === true
  ));
}

export function senderCanShareAvailability(accounts, senderAccountId) {
  const senderId = positiveInteger(senderAccountId);
  if (senderId === null) return false;
  return calendarScopedAvailabilityAccounts(accounts)
    .some(account => Number(account.id) === senderId);
}

export function defaultAvailabilityAccountIds(accounts, senderAccountId) {
  if (!senderCanShareAvailability(accounts, senderAccountId)) return [];
  return calendarScopedAvailabilityAccounts(accounts).map(account => Number(account.id));
}

function formatCivilDate(date) {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}`;
}

function civilDateInTimeZone(now, timeZone) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return new Date(Date.UTC(Number(values.year), Number(values.month) - 1, Number(values.day)));
}

export function availabilityDateRange(rangeDays, timeZone, now = new Date()) {
  const days = Number(rangeDays);
  if (!AVAILABILITY_RANGES.includes(days)) throw new Error('Choose a 7 or 14 day range.');
  if (!validAvailabilityTimeZone(timeZone)) throw new Error('Enter a valid IANA time zone.');
  const current = now instanceof Date ? now : new Date(now);
  if (Number.isNaN(current.getTime())) throw new Error('The current date is invalid.');
  const today = civilDateInTimeZone(current, timeZone);
  const start = new Date(today.getTime() + DAY_MS);
  const end = new Date(start.getTime() + (days - 1) * DAY_MS);
  return { start: formatCivilDate(start), end: formatCivilDate(end) };
}

function normalizeClock(value) {
  const clock = String(value || '').trim();
  const match = /^(\d{2}):(\d{2})$/.exec(clock);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return null;
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

function clockMinutes(value) {
  const normalized = normalizeClock(value);
  if (!normalized) return null;
  const [hour, minute] = normalized.split(':').map(Number);
  return hour * 60 + minute;
}

export function buildAvailabilityRequest({
  accountIds,
  senderAccountId,
  durationMinutes = 30,
  rangeDays = 7,
  dayStart = '09:00',
  dayEnd = '17:00',
  includeWeekends = false,
  timeZone = browserAvailabilityTimeZone(),
  now = new Date(),
} = {}) {
  const senderId = positiveInteger(senderAccountId);
  const normalizedIds = [...new Set((Array.isArray(accountIds) ? accountIds : [])
    .map(positiveInteger)
    .filter(id => id !== null))].sort((left, right) => left - right);
  if (senderId === null || !normalizedIds.includes(senderId)) {
    throw new Error('The sending account calendar must be included.');
  }
  if (normalizedIds.length === 0) throw new Error('Choose at least one calendar.');

  const duration = Number(durationMinutes);
  if (!AVAILABILITY_DURATIONS.includes(duration)) throw new Error('Choose a supported meeting length.');
  const start = normalizeClock(dayStart);
  const end = normalizeClock(dayEnd);
  if (!start || !end || clockMinutes(end) - clockMinutes(start) < duration) {
    throw new Error('Workday end must leave room for the meeting length.');
  }
  const range = availabilityDateRange(rangeDays, timeZone, now);
  return {
    account_ids: normalizedIds,
    start_date: range.start,
    end_date: range.end,
    timezone: String(timeZone).trim(),
    duration_minutes: duration,
    step_minutes: 30,
    day_start: start,
    day_end: end,
    include_weekends: includeWeekends === true,
    minimum_notice_minutes: 120,
  };
}

function normalizeCoverage(record) {
  const accountId = positiveInteger(record?.account_id);
  const accountEmail = String(record?.account_email || '').trim().toLowerCase();
  const state = String(record?.state || '');
  const lastSuccessAt = record?.last_success_at == null
    ? null
    : validIsoInstant(record.last_success_at);
  if (
    accountId === null
    || !accountEmail
    || !accountEmail.includes('@')
    || !AVAILABILITY_COVERAGE_STATES.includes(state)
    || (record?.last_success_at != null && !lastSuccessAt)
  ) throw new Error('Availability coverage response is invalid.');
  if (state === 'ready' && !lastSuccessAt) {
    throw new Error('Availability freshness response is incomplete.');
  }
  return {
    account_id: accountId,
    account_email: accountEmail,
    state,
    last_success_at: lastSuccessAt,
  };
}

function normalizeSlot(record, durationMinutes) {
  const start = validIsoInstant(record?.start);
  const end = validIsoInstant(record?.end);
  if (!start || !end) throw new Error('Availability slot response is invalid.');
  const duration = (new Date(end).getTime() - new Date(start).getTime()) / 60000;
  if (duration !== durationMinutes) throw new Error('Availability slot duration is invalid.');
  return { start, end };
}

export function normalizeAvailabilityResponse(response, {
  accountIds,
  timeZone,
  durationMinutes,
} = {}) {
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error('Availability response is invalid.');
  }
  const ready = response.ready;
  const generatedAt = validIsoInstant(response.generated_at);
  const responseTimeZone = String(response.timezone || '').trim();
  const responseDuration = Number(response.duration_minutes);
  if (
    typeof ready !== 'boolean'
    || !generatedAt
    || !validAvailabilityTimeZone(responseTimeZone)
    || !AVAILABILITY_DURATIONS.includes(responseDuration)
    || (timeZone && responseTimeZone !== timeZone)
    || (durationMinutes && responseDuration !== Number(durationMinutes))
    || !Array.isArray(response.coverage)
    || !Array.isArray(response.slots)
  ) throw new Error('Availability response is invalid.');

  const coverage = response.coverage.map(normalizeCoverage)
    .sort((left, right) => left.account_id - right.account_id);
  const coverageIds = coverage.map(item => item.account_id);
  if (new Set(coverageIds).size !== coverageIds.length) {
    throw new Error('Availability response contains duplicate calendars.');
  }
  const expectedIds = [...new Set((Array.isArray(accountIds) ? accountIds : [])
    .map(positiveInteger)
    .filter(id => id !== null))].sort((left, right) => left - right);
  if (
    expectedIds.length !== coverageIds.length
    || expectedIds.some((id, index) => id !== coverageIds[index])
  ) throw new Error('Availability response changed the requested calendar coverage.');

  const slots = response.slots.map(slot => normalizeSlot(slot, responseDuration))
    .sort((left, right) => left.start.localeCompare(right.start));
  const uniqueSlots = [];
  const slotKeys = new Set();
  for (const slot of slots) {
    const key = `${slot.start}|${slot.end}`;
    if (slotKeys.has(key)) throw new Error('Availability response contains duplicate times.');
    slotKeys.add(key);
    uniqueSlots.push(slot);
  }
  if (ready && coverage.some(item => item.state !== 'ready')) {
    throw new Error('Availability response overstates calendar coverage.');
  }
  if (!ready && uniqueSlots.length > 0) {
    throw new Error('Incomplete calendar coverage cannot return times.');
  }
  return {
    ready,
    generated_at: generatedAt,
    timezone: responseTimeZone,
    duration_minutes: responseDuration,
    coverage,
    slots: uniqueSlots.slice(0, MAX_AVAILABILITY_SLOTS),
  };
}

function dateFormatter(timeZone) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone,
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function timeFormatter(timeZone) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

function timestampFormatter(timeZone) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export function groupAvailabilitySlots(slots, timeZone) {
  if (!validAvailabilityTimeZone(timeZone)) throw new Error('Availability time zone is invalid.');
  const groups = [];
  for (const slot of Array.isArray(slots) ? slots : []) {
    const start = validIsoInstant(slot?.start);
    const end = validIsoInstant(slot?.end);
    if (!start || !end) continue;
    const dateLabel = dateFormatter(timeZone).format(new Date(start));
    let group = groups.at(-1);
    if (!group || group.label !== dateLabel) {
      group = { label: dateLabel, slots: [] };
      groups.push(group);
    }
    group.slots.push({
      start,
      end,
      label: `${timeFormatter(timeZone).format(new Date(start))} – ${timeFormatter(timeZone).format(new Date(end))}`,
    });
  }
  return groups;
}

export function availabilityCoverageMessage(record, timeZone) {
  const state = record?.state;
  const suffix = record?.last_success_at && validAvailabilityTimeZone(timeZone)
    ? ` Last synced ${timestampFormatter(timeZone).format(new Date(record.last_success_at))}.`
    : '';
  const messages = {
    ready: 'Calendar coverage is ready.',
    calendar_not_enabled: 'Calendar access is not enabled.',
    reauthorization_required: 'Calendar access must be reconnected.',
    sync_incomplete: 'The first calendar sync is incomplete.',
    stale: 'The saved calendar snapshot is stale.',
    sync_error: 'The calendar could not be synced.',
    syncing: 'The calendar is still syncing.',
  };
  return `${messages[state] || 'Calendar coverage is unavailable.'}${suffix}`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function formatAvailabilitySnapshot(response, selectedSlots) {
  const normalized = normalizeAvailabilityResponse(response, {
    accountIds: response?.coverage?.map(item => item.account_id),
    timeZone: response?.timezone,
    durationMinutes: response?.duration_minutes,
  });
  if (!normalized.ready) throw new Error('Calendar coverage is not ready.');

  const allowed = new Map(normalized.slots.map(slot => [`${slot.start}|${slot.end}`, slot]));
  const selected = [];
  const seen = new Set();
  for (const candidate of Array.isArray(selectedSlots) ? selectedSlots : []) {
    const key = `${validIsoInstant(candidate?.start)}|${validIsoInstant(candidate?.end)}`;
    const slot = allowed.get(key);
    if (!slot || seen.has(key)) continue;
    seen.add(key);
    selected.push(slot);
  }
  selected.sort((left, right) => left.start.localeCompare(right.start));
  if (selected.length === 0) throw new Error('Choose at least one time to insert.');
  if (selected.length > MAX_AVAILABILITY_SLOTS) throw new Error('Choose no more than 8 times.');

  const accounts = normalized.coverage.map(item => item.account_email);
  const lastSyncedAt = new Date(Math.min(...normalized.coverage.map(item => (
    new Date(item.last_success_at).getTime()
  )))).toISOString();
  const groups = groupAvailabilitySlots(selected, normalized.timezone);
  const introduction = `Here are a few times that work for me (${normalized.timezone}, ${normalized.duration_minutes} minutes):`;
  const plainLines = [introduction, ''];
  for (const group of groups) {
    plainLines.push(group.label, ...group.slots.map(slot => `• ${slot.label}`), '');
  }
  plainLines.push('Let me know what works best.');

  const htmlGroups = groups.map(group => (
    `<p><strong>${escapeHtml(group.label)}</strong></p><ul>${group.slots.map(slot => `<li>${escapeHtml(slot.label)}</li>`).join('')}</ul>`
  )).join('');
  return {
    text: plainLines.join('\n').trim(),
    html: `<div><p>${escapeHtml(introduction)}</p>${htmlGroups}<p>Let me know what works best.</p></div>`,
    accounts,
    lastSyncedAt,
    timeZone: normalized.timezone,
    durationMinutes: normalized.duration_minutes,
    slots: selected,
  };
}

export function availabilityPlainInsertion(value, snapshotText, caret) {
  const source = String(value ?? '');
  const text = String(snapshotText ?? '').replace(/\r\n?/g, '\n').trim();
  const insertionPoint = Math.max(0, Math.min(source.length, Number(caret) || 0));
  const before = insertionPoint > 0 && source[insertionPoint - 1] !== '\n' ? '\n\n' : '';
  const after = insertionPoint < source.length && source[insertionPoint] !== '\n' ? '\n\n' : '';
  const inserted = `${before}${text}${after}`;
  return { inserted, caret: insertionPoint + inserted.length };
}
