import assert from 'node:assert/strict';
import test from 'node:test';

import {
  calendarCoverage,
  calendarRangeCoveredByFullSync,
  calendarRequestDescriptor,
  calendarSyncHasActiveTarget,
  calendarSyncTargetsFinished,
  createCalendarSyncMonitor,
  createLatestRequestGate,
  getCalendarVisibleRange,
  shiftCalendarDate,
} from './calendarState.js';

test('month range exactly covers the rendered 42-day grid', () => {
  assert.deepEqual(
    getCalendarVisibleRange('month', new Date(2026, 1, 15)),
    { start: '2026-02-01', end: '2026-03-14' },
  );
  assert.deepEqual(
    getCalendarVisibleRange('month', new Date(2026, 10, 15)),
    { start: '2026-11-01', end: '2026-12-12' },
  );
  assert.deepEqual(
    getCalendarVisibleRange('month', new Date(2024, 1, 29)),
    { start: '2024-01-28', end: '2024-03-09' },
  );
});

test('sync monitoring keeps its submitted scope and requires every target to finish', () => {
  const accounts = [
    { id: 1, is_active: true, has_calendar_scope: true },
    { id: 2, is_active: true, has_calendar_scope: true },
  ];
  const baseline = [
    { account_id: 1, status: 'completed', last_incremental_sync: '2026-08-30T10:00:00Z' },
    { account_id: 2, status: 'completed', last_incremental_sync: '2026-08-30T10:00:00Z' },
  ];
  const monitor = createCalendarSyncMonitor({ accounts, statuses: baseline });
  assert.deepEqual(monitor.targetIds, [1, 2]);
  assert.equal(calendarSyncTargetsFinished(monitor, [
    { ...baseline[0], last_incremental_sync: '2026-08-30T10:01:00Z' },
    baseline[1],
  ]), false);
  assert.equal(calendarSyncTargetsFinished(monitor, [
    { ...baseline[0], last_incremental_sync: '2026-08-30T10:01:00Z' },
    { ...baseline[1], status: 'error' },
  ]), true);
});

test('sync monitoring accepts a target that was observed active and then idle', () => {
  const accounts = [{ id: 2, is_active: true, has_calendar_scope: true }];
  const baseline = [{ account_id: 2, status: 'completed', last_full_sync: '2026-08-30T10:00:00Z' }];
  const monitor = createCalendarSyncMonitor({ accounts, statuses: baseline, selectedAccountId: 2 });
  assert.equal(calendarSyncTargetsFinished(monitor, [{ ...baseline[0], status: 'syncing' }]), false);
  assert.equal(calendarSyncTargetsFinished(monitor, [{ ...baseline[0], status: 'idle' }]), true);
});

test('sync timeout copy can assert running only from the final target statuses', () => {
  const monitor = createCalendarSyncMonitor({
    accounts: [{ id: 2, is_active: true, has_calendar_scope: true }],
    statuses: [{ account_id: 2, status: 'completed', last_full_sync: '2026-08-30T10:00:00Z' }],
  });
  calendarSyncTargetsFinished(monitor, [{ account_id: 2, status: 'syncing' }]);
  assert.equal(monitor.sawActive.has(2), true);
  assert.equal(calendarSyncHasActiveTarget(monitor, []), false);
  assert.equal(calendarSyncHasActiveTarget(monitor, [{ account_id: 2, status: 'idle' }]), false);
  assert.equal(calendarSyncHasActiveTarget(monitor, [{ account_id: 2, status: 'syncing' }]), true);
  assert.equal(calendarSyncHasActiveTarget(monitor, [{ account_id: 99, status: 'syncing' }]), false);
});

test('week and day ranges cross year boundaries using local calendar days', () => {
  assert.deepEqual(
    getCalendarVisibleRange('week', new Date(2027, 0, 1)),
    { start: '2026-12-27', end: '2027-01-02' },
  );
  assert.deepEqual(
    getCalendarVisibleRange('day', new Date(2026, 7, 30)),
    { start: '2026-08-30', end: '2026-08-30' },
  );
});

test('month navigation clamps into the adjacent month instead of skipping it', () => {
  assert.equal(shiftCalendarDate('month', new Date(2026, 0, 31), 1).toDateString(), new Date(2026, 1, 28).toDateString());
  assert.equal(shiftCalendarDate('month', new Date(2024, 0, 31), 1).toDateString(), new Date(2024, 1, 29).toDateString());
  assert.equal(shiftCalendarDate('month', new Date(2026, 2, 31), -1).toDateString(), new Date(2026, 1, 28).toDateString());
  assert.equal(shiftCalendarDate('month', new Date(2026, 11, 15), 1).toDateString(), new Date(2027, 0, 15).toDateString());
});

test('request identity includes range, account, and display timezone', () => {
  const base = calendarRequestDescriptor({
    view: 'week', date: new Date(2026, 7, 30), accountId: 2, timeZone: 'America/New_York',
  });
  assert.deepEqual(base.params, {
    start: '2026-08-30', end: '2026-09-05', account_id: 2, tz: 'America/New_York',
  });
  assert.notEqual(base.key, calendarRequestDescriptor({
    view: 'week', date: new Date(2026, 7, 30), accountId: 1, timeZone: 'America/New_York',
  }).key);
  assert.notEqual(base.key, calendarRequestDescriptor({
    view: 'week', date: new Date(2026, 7, 30), accountId: 2, timeZone: 'UTC',
  }).key);
});

test('latest request gate invalidates the prior completion', () => {
  const gate = createLatestRequestGate();
  const first = gate.begin('first');
  const second = gate.begin('second');
  assert.equal(first.signal.aborted, true);
  assert.equal(first.isCurrent(), false);
  assert.equal(second.signal.aborted, false);
  assert.equal(second.isCurrent(), true);
  gate.cancel();
  assert.equal(second.isCurrent(), false);
});

test('coverage distinguishes verified empty from unavailable or unhealthy calendars', () => {
  const accounts = [
    { id: 1, is_active: true, has_calendar_scope: true },
    { id: 2, is_active: true, has_calendar_scope: true },
  ];
  const healthy = [
    { account_id: 1, status: 'completed', last_full_sync: '2026-08-30T12:00:00Z' },
    {
      account_id: 2,
      status: 'idle',
      last_full_sync: '2026-08-29T12:00:00Z',
      last_incremental_sync: '2026-08-30T11:00:00Z',
    },
  ];
  const range = { start: '2026-08-30', end: '2026-09-05' };
  assert.deepEqual(
    calendarCoverage({ accounts, statuses: healthy, statusState: 'ready', range }).state,
    'verified',
  );
  assert.equal(
    calendarCoverage({ accounts, statuses: healthy.slice(0, 1), statusState: 'ready', range }).state,
    'unverified',
  );
  assert.equal(
    calendarCoverage({
      accounts: [accounts[0]],
      statuses: [{ account_id: 1, status: 'idle', completed_at: '2026-08-30T12:00:00Z' }],
      statusState: 'ready',
      range,
    }).state,
    'unverified',
  );
  assert.equal(
    calendarCoverage({ accounts, statuses: [{ ...healthy[0], needs_reauth: true }, healthy[1]], statusState: 'ready', range }).state,
    'reauth',
  );
  assert.equal(
    calendarCoverage({ accounts, statuses: healthy, statusState: 'error', range }).state,
    'unknown',
  );
  assert.equal(
    calendarCoverage({
      accounts: [accounts[0], { ...accounts[1], has_calendar_scope: false }],
      statuses: healthy.slice(0, 1),
      statusState: 'ready',
      range,
    }).state,
    'partial',
  );
  assert.equal(
    calendarCoverage({
      accounts: [{ ...accounts[1], has_calendar_scope: false }],
      statuses: [],
      statusState: 'ready',
      range,
    }).state,
    'unavailable',
  );
});

test('account loading and failure never masquerade as no connected account', () => {
  assert.equal(calendarCoverage({ accounts: [], statusState: 'loading' }).state, 'checking');
  const failure = calendarCoverage({ accounts: [], statusState: 'accounts-error' });
  assert.equal(failure.state, 'unknown');
  assert.equal(failure.retry, 'accounts');
});

test('verified coverage is limited to every account full-sync window', () => {
  const statuses = [
    { account_id: 1, last_full_sync: '2026-08-30T12:00:00Z' },
    { account_id: 2, last_full_sync: '2026-08-29T12:00:00Z' },
  ];
  assert.equal(calendarRangeCoveredByFullSync({ start: '2026-08-30', end: '2026-09-05' }, statuses), true);
  assert.equal(calendarRangeCoveredByFullSync({ start: '2025-01-01', end: '2025-01-07' }, statuses), false);
  assert.equal(calendarRangeCoveredByFullSync({ start: '2027-12-01', end: '2027-12-07' }, statuses), false);
  assert.equal(calendarRangeCoveredByFullSync({ start: '2026-08-30', end: '2026-09-05' }, [
    { account_id: 1, last_incremental_sync: '2026-08-30T12:00:00Z' },
  ]), false);
});
