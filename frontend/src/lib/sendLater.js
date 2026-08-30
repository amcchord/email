const MIN_SCHEDULE_LEAD_MS = 60_000;

function localParts(date) {
  return [
    date.getFullYear(),
    date.getMonth() + 1,
    date.getDate(),
    date.getHours(),
    date.getMinutes(),
  ];
}

function sameParts(left, right) {
  return left.every((value, index) => value === right[index]);
}

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

export function browserScheduleTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
}

export function timezoneOffsetLabel(date) {
  const minutes = -date.getTimezoneOffset();
  const sign = minutes >= 0 ? '+' : '-';
  const absolute = Math.abs(minutes);
  return `UTC${sign}${String(Math.floor(absolute / 60)).padStart(2, '0')}:${String(absolute % 60).padStart(2, '0')}`;
}

export function formatScheduledDelivery(value, timezone = browserScheduleTimezone(), {
  compact = false,
} = {}) {
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) return 'Invalid schedule';
  try {
    const formatter = new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      weekday: compact ? undefined : 'short',
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    });
    return formatter.format(date);
  } catch {
    return new Intl.DateTimeFormat(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
    }).format(date);
  }
}

export function scheduledSendQuickChoices(nowValue = new Date()) {
  const now = new Date(nowValue);
  const candidates = [];
  const laterToday = localDateAt(now, 0, 15);
  if (laterToday.getTime() > now.getTime() + MIN_SCHEDULE_LEAD_MS) {
    candidates.push({ id: 'later-today', label: 'Later today', date: laterToday });
  }
  candidates.push(
    { id: 'tomorrow-morning', label: 'Tomorrow morning', date: localDateAt(now, 1, 9) },
    { id: 'tomorrow-afternoon', label: 'Tomorrow afternoon', date: localDateAt(now, 1, 15) },
  );
  const day = now.getDay();
  const daysUntilWorkday = day === 5 ? 3 : day === 6 ? 2 : 1;
  candidates.push({
    id: 'next-workday',
    label: daysUntilWorkday === 1 ? 'Next morning' : 'Monday morning',
    date: localDateAt(now, daysUntilWorkday, 9),
  });

  const seen = new Set();
  return candidates.filter(choice => {
    const instant = choice.date.getTime();
    if (instant <= now.getTime() + MIN_SCHEDULE_LEAD_MS || seen.has(instant)) return false;
    seen.add(instant);
    return true;
  }).map(choice => ({ ...choice, iso: choice.date.toISOString() }));
}

export function localScheduleInputValue(dateValue = new Date(Date.now() + 60 * 60 * 1000)) {
  const date = new Date(dateValue);
  const pad = value => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function resolveLocalSchedule(value, nowValue = new Date()) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(String(value || ''));
  if (!match) return { error: 'Choose a date and time.' };
  const requested = match.slice(1).map(Number);
  const first = new Date(
    requested[0],
    requested[1] - 1,
    requested[2],
    requested[3],
    requested[4],
    0,
    0,
  );
  if (!sameParts(localParts(first), requested)) {
    return { error: 'That local time does not exist because the clock changes then.' };
  }
  const now = new Date(nowValue);
  const candidates = [first];
  // Modern zones do not all move by one hour (for example Lord Howe moves by
  // 30 minutes). Scan the bounded fold window minute-by-minute so every exact
  // repeated wall time is offered without guessing the jurisdiction's offset.
  for (let minute = 1; minute <= 180; minute += 1) {
    const repeated = new Date(first.getTime() + minute * 60_000);
    if (
      sameParts(localParts(repeated), requested)
      && repeated.getTimezoneOffset() !== first.getTimezoneOffset()
    ) {
      candidates.push(repeated);
    }
  }
  const future = candidates.filter(date => date.getTime() > now.getTime() + MIN_SCHEDULE_LEAD_MS);
  if (!future.length) return { error: 'Choose a time at least one minute from now.' };
  return {
    candidates: future.map(date => ({
      date,
      iso: date.toISOString(),
      offsetLabel: timezoneOffsetLabel(date),
    })),
  };
}
