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
