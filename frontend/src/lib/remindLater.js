import {
  browserScheduleTimezone,
  formatScheduledDelivery,
  localScheduleInputValue,
  resolveLocalSchedule,
} from './sendLater.js';

const MIN_REMINDER_LEAD_MS = 60_000;

function localDateAt(base, dayOffset, hour, minute = 0) {
  return new Date(
    base.getFullYear(),
    base.getMonth(),
    base.getDate() + dayOffset,
    hour,
    minute,
    0,
    0,
  );
}

export {
  browserScheduleTimezone,
  formatScheduledDelivery,
  localScheduleInputValue,
  resolveLocalSchedule,
};

/**
 * Stable, calendar-based choices for returning a message to the inbox.
 * Local Date construction deliberately follows the browser's civil timezone;
 * every returned value is immediately serialized to an absolute UTC instant.
 */
export function snoozeQuickChoices(nowValue = new Date()) {
  const now = new Date(nowValue);
  const nextMinute = now.getTime() + MIN_REMINDER_LEAD_MS;
  const laterTodayHour = Math.min(20, Math.max(now.getHours() + 3, 15));
  const laterToday = localDateAt(now, 0, laterTodayHour);
  const choices = [];

  if (laterToday.getTime() > nextMinute) {
    choices.push({ id: 'later-today', label: 'Later today', date: laterToday });
  }

  choices.push({
    id: 'tomorrow',
    label: 'Tomorrow morning',
    date: localDateAt(now, 1, 9),
  });

  const day = now.getDay();
  const daysUntilNextWeek = 8 - day;
  choices.push({
    id: 'next-week',
    label: 'Next week',
    date: localDateAt(now, daysUntilNextWeek, 9),
  });

  const seen = new Set();
  return choices
    .filter(choice => choice.date.getTime() > nextMinute && !seen.has(choice.date.getTime()))
    .map(choice => {
      seen.add(choice.date.getTime());
      return { ...choice, iso: choice.date.toISOString() };
    });
}

export function formatSnoozeWake(value, timezone = browserScheduleTimezone(), options = {}) {
  return formatScheduledDelivery(value, timezone, options);
}
