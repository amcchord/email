import assert from 'node:assert/strict';
import test from 'node:test';
import {
  resolveLocalSchedule,
  snoozeQuickChoices,
} from './remindLater.js';

process.env.TZ = 'America/New_York';

test('snooze choices expose later today, tomorrow, and next week as unique instants', () => {
  const now = new Date('2026-08-30T10:00:00-04:00');
  const choices = snoozeQuickChoices(now);

  assert.deepEqual(choices.map(choice => choice.id), ['later-today', 'tomorrow', 'next-week']);
  assert.equal(new Set(choices.map(choice => choice.iso)).size, choices.length);
  assert.ok(choices.every(choice => Date.parse(choice.iso) > now.getTime() + 60_000));
});

test('late-evening snooze choices omit an impossible later-today option', () => {
  const choices = snoozeQuickChoices(new Date('2026-08-30T21:30:00-04:00'));
  assert.deepEqual(choices.map(choice => choice.id), ['tomorrow', 'next-week']);
});

test('custom reminders share scheduled-send DST gap and fold handling', () => {
  const gap = resolveLocalSchedule(
    '2026-03-08T02:30',
    new Date('2026-03-01T12:00:00-05:00'),
  );
  assert.match(gap.error, /does not exist/);

  const fold = resolveLocalSchedule(
    '2026-11-01T01:30',
    new Date('2026-10-01T12:00:00-04:00'),
  );
  assert.equal(fold.candidates.length, 2);
  assert.notEqual(fold.candidates[0].offsetLabel, fold.candidates[1].offsetLabel);
});

