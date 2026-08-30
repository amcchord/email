export function isWebLocation(value) {
  return /^https?:\/\//i.test((value || '').trim());
}

export function locationLabel(event) {
  if (!event?.location) return '';
  if (isWebLocation(event.location)) return 'Video call';
  return event.location;
}

export function videoCallUrl(event) {
  if (event?.hangout_link) return event.hangout_link;
  return isWebLocation(event?.location) ? event.location : '';
}

export function inclusiveAllDayEnd(startDate, exclusiveEndDate) {
  if (!exclusiveEndDate || exclusiveEndDate <= startDate) return startDate;
  const [year, month, day] = exclusiveEndDate.split('-').map(Number);
  if (!year || !month || !day) return startDate;
  const inclusive = new Date(year, month - 1, day - 1);
  return `${inclusive.getFullYear()}-${String(inclusive.getMonth() + 1).padStart(2, '0')}-${String(inclusive.getDate()).padStart(2, '0')}`;
}

export function timedEventsForDay(events, date) {
  const dayStart = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayEnd = new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1);

  return (events || []).flatMap(event => {
    if (event?.is_all_day || !event?.start_time) return [];
    const start = new Date(event.start_time);
    if (Number.isNaN(start.getTime())) return [];
    const parsedEnd = event.end_time ? new Date(event.end_time) : null;
    const end = parsedEnd && !Number.isNaN(parsedEnd.getTime())
      ? parsedEnd
      : new Date(start.getTime() + 60 * 60 * 1000);
    if (start >= dayEnd || end <= dayStart) return [];

    const clippedStart = start < dayStart ? dayStart : start;
    const clippedEnd = end > dayEnd ? dayEnd : end;
    return [{
      ...event,
      start_time: clippedStart.toISOString(),
      end_time: clippedEnd.toISOString(),
      _sourceEvent: event._sourceEvent || event,
      _continuesBefore: start < dayStart,
      _continuesAfter: end > dayEnd,
    }];
  });
}

export function sourceCalendarEvent(event) {
  return event?._sourceEvent || event;
}
