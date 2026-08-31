import assert from 'node:assert/strict';
import test from 'node:test';

import {
  adjustInboxSectionTotals,
  combineInboxSections,
  isSplitInboxActive,
  mergeInboxSectionPages,
  nextInboxSectionFocus,
  normalizeInboxSectionResult,
  placementReasonLabel,
} from './focusedInbox.js';

const focused = id => ({ id, inbox_placement: 'focused' });
const other = id => ({ id, inbox_placement: 'other' });

test('Split Inbox is confined to the literal unfiltered Inbox', () => {
  assert.equal(isSplitInboxActive({ hideIgnored: true, mailbox: 'INBOX' }), true);
  assert.equal(isSplitInboxActive({ hideIgnored: true, mailbox: 'ALL' }), false);
  assert.equal(isSplitInboxActive({ hideIgnored: true, mailbox: 'INBOX', search: 'roadmap' }), false);
  assert.equal(isSplitInboxActive({ hideIgnored: true, mailbox: 'INBOX', smartFilter: { type: 'needs_reply' } }), false);
});

test('section responses are fail-closed and combine with exact totals', () => {
  const focusedResult = normalizeInboxSectionResult({
    emails: [focused(1), focused(2)], total: 3, page: 1, page_size: 2,
  }, 'focused');
  const otherResult = normalizeInboxSectionResult({
    emails: [other(3)], total: 1, page: 1, page_size: 2,
  }, 'other');
  const combined = combineInboxSections(focusedResult, otherResult);

  assert.deepEqual(combined.emails.map(item => item.id), [1, 2, 3]);
  assert.deepEqual(combined.sectionTotals, { focused: 3, other: 1 });
  assert.equal(combined.total, 4);
  assert.equal(combined.hasMore, true);
  assert.throws(
    () => normalizeInboxSectionResult({ emails: [other(9)] }, 'focused'),
    /did not match/,
  );
  assert.throws(
    () => combineInboxSections(
      { emails: [{ ...focused(9), conversation_key: '7:thread:shared' }], total: 1 },
      { emails: [{ ...other(10), conversation_key: '7:thread:shared' }], total: 1 },
    ),
    /same conversation/,
  );
});

test('appended section pages preserve Focused then Other and deduplicate', () => {
  const merged = mergeInboxSectionPages(
    [focused(1), focused(2), other(10)],
    [focused(2), focused(3), other(10), other(11)],
  );
  assert.deepEqual(merged.map(item => item.id), [1, 2, 3, 10, 11]);
});

test('section navigation wraps between populated sections', () => {
  const emails = [focused(1), focused(2), other(10), other(11)];
  assert.equal(nextInboxSectionFocus(emails, 2, 1), 10);
  assert.equal(nextInboxSectionFocus(emails, 10, -1), 1);
  assert.equal(nextInboxSectionFocus(emails, 11, 1), 1);
  assert.equal(nextInboxSectionFocus([other(10)], null, -1), 10);
});

test('optimistic totals follow removed and restored placements', () => {
  const removed = [focused(1), other(10)];
  const totals = adjustInboxSectionTotals({ focused: 4, other: 2 }, removed, -1);
  assert.deepEqual(totals, { focused: 3, other: 1 });
  assert.deepEqual(adjustInboxSectionTotals(totals, removed, 1), { focused: 4, other: 2 });
});

test('placement reasons are concise and unknown values stay quiet', () => {
  assert.equal(placementReasonLabel('needs_reply'), 'Needs reply');
  assert.equal(placementReasonLabel('delegated_scheduling'), 'Delegated scheduling');
  assert.equal(placementReasonLabel('unknown'), '');
});
