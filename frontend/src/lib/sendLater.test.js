import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatScheduledDelivery,
  resolveLocalSchedule,
  scheduledSendQuickChoices,
} from './sendLater.js';

process.env.TZ = 'America/New_York';

test('quick choices are future, unique, and carry absolute instants', () => {
  const now = new Date('2026-08-30T12:00:00-04:00');
  const choices = scheduledSendQuickChoices(now);
  const instants = choices.map(choice => Date.parse(choice.iso));

  assert.ok(choices.length >= 3);
  assert.equal(new Set(instants).size, instants.length);
  assert.ok(instants.every(instant => instant > now.getTime() + 60_000));
});

test('custom scheduling rejects a nonexistent spring-forward wall time', () => {
  const result = resolveLocalSchedule(
    '2026-03-08T02:30',
    new Date('2026-03-01T12:00:00-05:00'),
  );
  assert.match(result.error, /does not exist/);
});

test('custom scheduling exposes both fall-back occurrences as distinct instants', () => {
  const result = resolveLocalSchedule(
    '2026-11-01T01:30',
    new Date('2026-10-01T12:00:00-04:00'),
  );

  assert.equal(result.candidates.length, 2);
  assert.equal(result.candidates[1].date.getTime() - result.candidates[0].date.getTime(), 3_600_000);
  assert.notEqual(result.candidates[0].offsetLabel, result.candidates[1].offsetLabel);
  assert.match(
    formatScheduledDelivery(result.candidates[0].iso, 'America/New_York'),
    /EDT/,
  );
  assert.match(
    formatScheduledDelivery(result.candidates[1].iso, 'America/New_York'),
    /EST/,
  );
});

test('custom scheduling handles a non-one-hour fall-back fold', () => {
  const previous = process.env.TZ;
  process.env.TZ = 'Australia/Lord_Howe';
  try {
    const result = resolveLocalSchedule(
      '2026-04-05T01:45',
      new Date('2026-03-01T12:00:00+11:00'),
    );
    assert.equal(result.candidates.length, 2);
    assert.equal(result.candidates[1].date.getTime() - result.candidates[0].date.getTime(), 1_800_000);
    assert.notEqual(result.candidates[0].offsetLabel, result.candidates[1].offsetLabel);
  } finally {
    process.env.TZ = previous || 'America/New_York';
  }
});
