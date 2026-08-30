const DAY_MS = 24 * 60 * 60 * 1000;

export function formatCalendarDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function addLocalDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

export function getCalendarVisibleRange(view, date) {
  const year = date.getFullYear();
  const month = date.getMonth();
  const day = date.getDate();

  if (view === 'month') {
    const first = new Date(year, month, 1);
    const start = new Date(year, month, 1 - first.getDay());
    return {
      start: formatCalendarDate(start),
      end: formatCalendarDate(addLocalDays(start, 41)),
    };
  }

  if (view === 'week') {
    const start = new Date(year, month, day - date.getDay());
    return {
      start: formatCalendarDate(start),
      end: formatCalendarDate(addLocalDays(start, 6)),
    };
  }

  const formatted = formatCalendarDate(date);
  return { start: formatted, end: formatted };
}

export function shiftCalendarDate(view, date, direction) {
  if (view === 'month') {
    const targetMonth = date.getMonth() + direction;
    const lastTargetDay = new Date(date.getFullYear(), targetMonth + 1, 0).getDate();
    return new Date(
      date.getFullYear(),
      targetMonth,
      Math.min(date.getDate(), lastTargetDay),
    );
  }

  const days = view === 'week' ? 7 * direction : direction;
  return addLocalDays(date, days);
}

export function calendarRequestDescriptor({ view, date, accountId = null, timeZone = 'UTC' }) {
  const range = getCalendarVisibleRange(view, date);
  const normalizedAccountId = Number.isInteger(accountId) && accountId > 0 ? accountId : null;
  const normalizedTimeZone = timeZone || 'UTC';
  const params = {
    start: range.start,
    end: range.end,
    tz: normalizedTimeZone,
  };
  if (normalizedAccountId !== null) params.account_id = normalizedAccountId;

  return {
    key: [view, range.start, range.end, normalizedAccountId ?? 'all', normalizedTimeZone].join('|'),
    params,
    range,
  };
}

export function createLatestRequestGate() {
  let generation = 0;
  let controller = null;

  return {
    begin(key) {
      generation += 1;
      controller?.abort();
      controller = new AbortController();
      const currentGeneration = generation;
      return {
        key,
        signal: controller.signal,
        isCurrent: () => currentGeneration === generation && !controller.signal.aborted,
      };
    },
    cancel() {
      generation += 1;
      controller?.abort();
      controller = null;
    },
  };
}

function syncTimestamp(status) {
  // completed_at is also written for failed syncs, so it cannot certify data.
  return status?.last_incremental_sync || status?.last_full_sync || null;
}

function parseCalendarDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

function offsetUtcDays(date, days) {
  return new Date(date.getTime() + days * DAY_MS);
}

export function calendarRangeCoveredByFullSync(range, statuses = []) {
  const rangeStart = parseCalendarDate(range?.start);
  const rangeEnd = parseCalendarDate(range?.end);
  if (!rangeStart || !rangeEnd || rangeEnd < rangeStart || statuses.length === 0) return false;

  return statuses.every(status => {
    if (!status?.last_full_sync) return false;
    const fullSync = new Date(status.last_full_sync);
    if (Number.isNaN(fullSync.getTime())) return false;
    const anchor = new Date(Date.UTC(
      fullSync.getUTCFullYear(),
      fullSync.getUTCMonth(),
      fullSync.getUTCDate(),
    ));
    // The service ingests now-180d through now+365d. Keep a one-day safety
    // margin for timezone/day-boundary overlap before certifying an empty view.
    const coveredStart = offsetUtcDays(anchor, -179);
    const coveredEnd = offsetUtcDays(anchor, 364);
    return rangeStart >= coveredStart && rangeEnd <= coveredEnd;
  });
}

export function calendarCoverage({ accounts = [], selectedAccountId = null, statuses = [], statusState = 'loading', range = null }) {
  const activeAccounts = accounts.filter(account => account?.is_active !== false);
  const selected = selectedAccountId === null
    ? activeAccounts
    : activeAccounts.filter(account => account.id === selectedAccountId);

  // Account authority has not been established yet. Loading/error must win
  // over the empty array placeholder so it never masquerades as "no account".
  if (statusState === 'loading') {
    return { state: 'checking', message: 'Checking connected calendars…', accounts: selected };
  }
  if (statusState === 'accounts-error') {
    return {
      state: 'unknown',
      message: 'Connected calendars could not be loaded.',
      accounts: selected,
      retry: 'accounts',
    };
  }

  if (selected.length === 0) {
    return {
      state: 'unavailable',
      message: selectedAccountId === null
        ? 'No connected account is available for Calendar.'
        : 'This account is not available for Calendar.',
      accounts: selected,
    };
  }

  const statusByAccount = new Map(statuses.map(status => [status.account_id, status]));
  const reauth = selected.filter(account => statusByAccount.get(account.id)?.needs_reauth);
  if (reauth.length > 0) {
    return {
      state: 'reauth',
      message: `${reauth.length} calendar${reauth.length === 1 ? '' : 's'} need to be reconnected.`,
      accounts: reauth,
    };
  }

  const withoutScope = selected.filter(account => account?.has_calendar_scope === false);
  if (withoutScope.length > 0) {
    const partial = withoutScope.length < selected.length;
    return {
      state: partial ? 'partial' : 'unavailable',
      message: partial
        ? `${withoutScope.length} visible calendar${withoutScope.length === 1 ? ' is' : 's are'} not connected.`
        : 'Calendar access is not connected for this account.',
      accounts: withoutScope,
    };
  }

  if (statusState === 'error') {
    return {
      state: 'unknown',
      message: 'Calendar freshness could not be verified.',
      accounts: selected,
    };
  }
  const missing = selected.filter(account => !statusByAccount.has(account.id));
  const failed = selected.filter(account => {
    const status = statusByAccount.get(account.id);
    return status?.status === 'error' && !status?.needs_reauth;
  });
  const syncing = selected.filter(account => statusByAccount.get(account.id)?.status === 'syncing');

  if (failed.length > 0) {
    return {
      state: 'degraded',
      message: `${failed.length} calendar${failed.length === 1 ? '' : 's'} could not sync.`,
      accounts: failed,
    };
  }
  if (syncing.length > 0) {
    return {
      state: 'syncing',
      message: `${syncing.length} calendar${syncing.length === 1 ? ' is' : 's are'} syncing.`,
      accounts: syncing,
    };
  }
  if (missing.length > 0) {
    return {
      state: 'unverified',
      message: `${missing.length} calendar${missing.length === 1 ? ' has' : 's have'} not completed an initial sync.`,
      accounts: missing,
    };
  }

  const timestamps = selected
    .map(account => syncTimestamp(statusByAccount.get(account.id)))
    .filter(Boolean)
    .map(value => new Date(value))
    .filter(value => !Number.isNaN(value.getTime()));
  if (timestamps.length !== selected.length) {
    return {
      state: 'unverified',
      message: 'Calendar freshness has not been established yet.',
      accounts: selected,
    };
  }

  const oldestTimestamp = new Date(Math.min(...timestamps.map(value => value.getTime())));
  const selectedStatuses = selected.map(account => statusByAccount.get(account.id));
  if (!calendarRangeCoveredByFullSync(range, selectedStatuses)) {
    return {
      state: 'unverified',
      message: 'This range is outside the calendars’ confirmed saved window.',
      accounts: selected,
      oldestTimestamp: oldestTimestamp.toISOString(),
    };
  }
  return {
    state: 'verified',
    message: 'All visible calendars have completed a sync.',
    accounts: selected,
    oldestTimestamp: oldestTimestamp.toISOString(),
  };
}

export function isCalendarAbort(error) {
  return error?.name === 'AbortError';
}

export function successfulCalendarSyncTimestamp(status) {
  return status?.last_incremental_sync || status?.last_full_sync || null;
}

export function createCalendarSyncMonitor({ accounts = [], statuses = [], selectedAccountId = null }) {
  const targetIds = accounts
    .filter(account =>
      account?.is_active !== false
      && account?.has_calendar_scope !== false
      && (selectedAccountId === null || account.id === selectedAccountId)
    )
    .map(account => account.id);
  const statusByAccount = new Map(statuses.map(status => [status.account_id, status]));
  return {
    targetIds,
    baselineByAccount: new Map(targetIds.map(accountId => [
      accountId,
      successfulCalendarSyncTimestamp(statusByAccount.get(accountId)),
    ])),
    sawActive: new Set(),
  };
}

export function calendarSyncTargetsFinished(context, statuses = []) {
  const statusByAccount = new Map(statuses.map(status => [status.account_id, status]));
  for (const accountId of context.targetIds) {
    if (statusByAccount.get(accountId)?.status === 'syncing') context.sawActive.add(accountId);
  }
  return context.targetIds.length > 0 && context.targetIds.every(accountId => {
    const status = statusByAccount.get(accountId);
    if (!status) return false;
    if (status.needs_reauth || status.status === 'error') return true;
    if (status.status === 'syncing') return false;
    const baseline = context.baselineByAccount.get(accountId) || null;
    const latest = successfulCalendarSyncTimestamp(status);
    return context.sawActive.has(accountId) || (latest && latest !== baseline);
  });
}

export function calendarSyncHasActiveTarget(context, statuses = []) {
  const targetIds = new Set(context?.targetIds || []);
  return statuses.some(status => targetIds.has(status?.account_id) && status?.status === 'syncing');
}

export const CALENDAR_DAY_MS = DAY_MS;
