const NAMED_ENTITIES = {
  amp: '&', apos: "'", gt: '>', hellip: '…', lt: '<', nbsp: ' ', quot: '"',
};

/** Decode mail-header/snippet entities and strip invisible tracking padding. */
export function cleanEmailText(value) {
  if (!value) return '';
  return String(value)
    .replace(/&#(x[0-9a-f]+|\d+);?/gi, (_, code) => {
      const number = code[0].toLowerCase() === 'x'
        ? Number.parseInt(code.slice(1), 16)
        : Number.parseInt(code, 10);
      return Number.isFinite(number) ? String.fromCodePoint(number) : '';
    })
    .replace(/&([a-z]+);/gi, (match, name) => NAMED_ENTITIES[name.toLowerCase()] ?? match)
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')
    .replace(/[\u00A0\t\r\n ]+/g, ' ')
    .trim();
}

const CATEGORY_LABELS = {
  urgent: 'Urgent',
  can_ignore: 'Low priority',
  fyi: 'FYI',
  awaiting_reply: 'Awaiting reply',
};

export function categoryLabel(value) {
  if (!value) return '';
  return CATEGORY_LABELS[value] || value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
}

export function typeLabel(value) {
  if (!value) return '';
  return value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
}
