import assert from 'node:assert/strict';
import test from 'node:test';

import { inclusiveAllDayEnd, sourceCalendarEvent, timedEventsForDay } from './calendarDisplay.js';

test('Google all-day exclusive ends are converted to inclusive display dates', () => {
  assert.equal(inclusiveAllDayEnd('2026-09-02', '2026-09-03'), '2026-09-02');
  assert.equal(inclusiveAllDayEnd('2026-09-02', '2026-09-06'), '2026-09-05');
  assert.equal(inclusiveAllDayEnd('2026-12-31', '2027-01-02'), '2027-01-01');
  assert.equal(inclusiveAllDayEnd('2026-09-02', null), '2026-09-02');
});

test('timed events are clipped into every local day they overlap', () => {
  const source = {
    id: 1,
    is_all_day: false,
    start_time: '2026-08-31T03:30:00Z', // Aug 30 11:30 PM in New York
    end_time: '2026-08-31T05:45:00Z',   // Aug 31 1:45 AM in New York
  };
  const first = timedEventsForDay([source], new Date(2026, 7, 30));
  const second = timedEventsForDay([source], new Date(2026, 7, 31));
  assert.equal(first.length, 1);
  assert.equal(second.length, 1);
  assert.equal(first[0]._continuesAfter, true);
  assert.equal(second[0]._continuesBefore, true);
  assert.equal(sourceCalendarEvent(second[0]), source);
});

test('timed events use half-open day boundaries', () => {
  const day = new Date(2026, 7, 30);
  const endingAtStart = {
    id: 1, is_all_day: false,
    start_time: new Date(2026, 7, 29, 23, 0).toISOString(),
    end_time: new Date(2026, 7, 30, 0, 0).toISOString(),
  };
  const startingAtEnd = {
    id: 2, is_all_day: false,
    start_time: new Date(2026, 7, 31, 0, 0).toISOString(),
    end_time: new Date(2026, 7, 31, 1, 0).toISOString(),
  };
  assert.deepEqual(timedEventsForDay([endingAtStart, startingAtEnd], day), []);
});
