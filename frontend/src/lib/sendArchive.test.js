import assert from 'node:assert/strict';
import test from 'node:test';

import {
  SEND_ARCHIVE_UNAVAILABLE_MESSAGE,
  canArchiveAfterSend,
  exactSourceEmailId,
  sendArchiveAcceptedMessage,
  withArchiveAfterSend,
} from './sendArchive.js';

test('archive-after-send requires one exact positive source id', () => {
  assert.equal(exactSourceEmailId(41), 41);
  for (const value of [null, undefined, 0, -1, 1.5, '41']) {
    assert.equal(exactSourceEmailId(value), null);
  }
  assert.equal(canArchiveAfterSend({ source_email_id: 41 }), true);
  assert.equal(canArchiveAfterSend({ thread_id: 'generated-thread' }), false);
});

test('ordinary send remains unchanged and never carries a stale archive flag', () => {
  const source = {
    account_id: 7,
    source_email_id: 41,
    body_text: 'Generated reply',
    archive_source_after_send: true,
  };
  const payload = withArchiveAfterSend(source, false);

  assert.deepEqual(payload, {
    account_id: 7,
    source_email_id: 41,
    body_text: 'Generated reply',
  });
  assert.notEqual(payload, source);
});

test('send and scheduled-send preserve every field while adding durable archive intent', () => {
  const source = {
    account_id: 7,
    source_email_id: 41,
    body_text: 'Generated reply',
    scheduled_for: '2026-08-31T13:00:00.000Z',
    schedule_timezone: 'America/New_York',
  };
  assert.deepEqual(withArchiveAfterSend(source, true), {
    ...source,
    archive_source_after_send: true,
  });
});

test('archive intent fails closed without inferring from thread or account context', () => {
  assert.throws(
    () => withArchiveAfterSend({ account_id: 7, thread_id: 'generated-thread' }, true),
    error => error.code === 'send_archive_source_unavailable'
      && error.message === SEND_ARCHIVE_UNAVAILABLE_MESSAGE,
  );
});

test('accepted copy says delivery confirmation owns the archive boundary', () => {
  assert.match(sendArchiveAcceptedMessage(), /only after delivery is confirmed/);
  assert.match(sendArchiveAcceptedMessage({ scheduled: true }), /^Scheduled;/);
});
