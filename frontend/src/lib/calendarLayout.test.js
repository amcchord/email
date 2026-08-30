import assert from 'node:assert/strict';
import test from 'node:test';

import { timedEventsForDay } from './calendarDisplay.js';
import { calendarEventMinuteRange, layoutEvents } from './calendarLayout.js';

test('a segment clipped at next-day midnight uses minute 1440', () => {
  const event = {
    id: 1,
    start_time: new Date(2026, 7, 30, 23, 30).toISOString(),
    end_time: new Date(2026, 7, 31, 1, 0).toISOString(),
  };
  const [segment] = timedEventsForDay([event], new Date(2026, 7, 30));
  assert.deepEqual(calendarEventMinuteRange(segment), { startMin: 23 * 60 + 30, endMin: 1440 });
  const [position] = layoutEvents([segment], 60);
  assert.equal(position.top, 23 * 60 + 30);
  assert.equal(position.height, 30);
});

test('a full middle-day segment fills the 24-hour visual grid', () => {
  const event = {
    id: 2,
    start_time: new Date(2026, 7, 29, 12, 0).toISOString(),
    end_time: new Date(2026, 8, 1, 0, 0).toISOString(),
  };
  const [segment] = timedEventsForDay([event], new Date(2026, 7, 30));
  const [position] = layoutEvents([segment], 60);
  assert.equal(position.top, 0);
  assert.equal(position.height, 1440);
});
