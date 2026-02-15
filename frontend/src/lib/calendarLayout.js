/**
 * Shared calendar layout utilities: event merging, classification, and positioning.
 */

/**
 * Jaccard token similarity between two strings.
 * Tokenizes by splitting on whitespace, lowercasing, and computing
 * |intersection| / |union| of the token sets.
 */
function jaccardSimilarity(a, b) {
  const tokensA = new Set(a.toLowerCase().split(/\s+/).filter(Boolean));
  const tokensB = new Set(b.toLowerCase().split(/\s+/).filter(Boolean));
  if (tokensA.size === 0 && tokensB.size === 0) return 1;
  if (tokensA.size === 0 || tokensB.size === 0) return 0;
  let intersection = 0;
  for (const t of tokensA) {
    if (tokensB.has(t)) intersection++;
  }
  const union = tokensA.size + tokensB.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

/**
 * Deduplicate cross-account events.
 * Groups events by exact (start_time, end_time) pairs, then merges
 * events from different accounts that have the same organizer or
 * title similarity > 60%.
 *
 * Merged events gain a `_mergedAccounts` array of all account emails.
 * Non-duplicates pass through with `_mergedAccounts` set to their single account.
 */
export function mergeEvents(events) {
  if (!events || events.length === 0) return [];

  // Group by time key
  const byTime = new Map();
  for (const e of events) {
    const startKey = e.start_time || e.start_date || '';
    const endKey = e.end_time || e.end_date || '';
    const key = `${startKey}|${endKey}`;
    if (!byTime.has(key)) byTime.set(key, []);
    byTime.get(key).push(e);
  }

  const result = [];
  for (const group of byTime.values()) {
    if (group.length === 1) {
      result.push({ ...group[0], _mergedAccounts: [group[0].account_email] });
      continue;
    }

    // Within a time group, try to merge events from different accounts
    const merged = [];
    const used = new Set();

    for (let i = 0; i < group.length; i++) {
      if (used.has(i)) continue;
      const base = { ...group[i], _mergedAccounts: [group[i].account_email] };

      for (let j = i + 1; j < group.length; j++) {
        if (used.has(j)) continue;
        const candidate = group[j];

        // Skip if same account
        if (candidate.account_email === base.account_email) continue;

        // Check merge criteria: same organizer OR title similarity > 60%
        const sameOrganizer = base.organizer_email && candidate.organizer_email &&
          base.organizer_email === candidate.organizer_email;
        const titleSim = jaccardSimilarity(
          base.summary || '',
          candidate.summary || ''
        );

        if (sameOrganizer || titleSim > 0.6) {
          base._mergedAccounts.push(candidate.account_email);
          used.add(j);
        }
      }

      used.add(i);
      merged.push(base);
    }

    result.push(...merged);
  }

  return result;
}

const BACKGROUND_PATTERNS = [
  /\bunavailable\b/i,
  /\bdo\s+not\s+schedule\b/i,
  /\bblock(er|ed)?\b/i,
  /\bout\s+of\s+office\b/i,
  /\booo\b/i,
  /\bbusy\b/i,
];

/**
 * Classify an event as 'background' or 'normal'.
 * Background events are long blockers (>= 4h) or title-matched patterns.
 */
export function classifyEvent(event) {
  // Check title patterns
  const title = event.summary || '';
  for (const pat of BACKGROUND_PATTERNS) {
    if (pat.test(title)) return 'background';
  }

  // Check duration >= 4 hours
  if (event.start_time && event.end_time) {
    const start = new Date(event.start_time);
    const end = new Date(event.end_time);
    const hours = (end - start) / (1000 * 60 * 60);
    if (hours >= 4) return 'background';
  }

  return 'normal';
}

/**
 * Compute layout positions for a single day's timed events.
 *
 * Two tiers:
 *   1. Background — full width, low z-index, translucent (long blocks, OOO, etc.)
 *   2. Foreground — merged (multi-account) AND normal events together in one
 *      unified column layout so every event gets its own visible space.
 *
 * @param {Array} events - Array of timed events (already merged)
 * @param {number} pxPerHour - Pixels per hour for vertical positioning
 * @returns {Array} Array of { event, top, height, left, width, zIndex, isBackground, isMerged }
 */
export function layoutEvents(events, pxPerHour) {
  if (!events || events.length === 0) return [];

  const result = [];

  // Separate into 2 tiers: background and foreground (merged + normal together).
  // Merged (multi-account) events are always foreground so they stay visible —
  // if something appears on multiple calendars it's important enough to show.
  const bgEvents = [];
  const fgEvents = [];

  for (const e of events) {
    const isMerged = e._mergedAccounts && e._mergedAccounts.length > 1;
    if (!isMerged && classifyEvent(e) === 'background') {
      bgEvents.push(e);
    } else {
      fgEvents.push(e);
    }
  }

  // Tier 1: Background events — full width, low z-index, rendered translucent
  for (const e of bgEvents) {
    const pos = computePosition(e, pxPerHour);
    result.push({
      event: e,
      top: pos.top,
      height: pos.height,
      left: '0%',
      width: '100%',
      zIndex: 5,
      isBackground: true,
      isMerged: (e._mergedAccounts && e._mergedAccounts.length > 1),
    });
  }

  // Tier 2: All foreground events (merged + normal) with unified overlap detection
  if (fgEvents.length > 0) {
    const items = fgEvents.map(e => {
      const start = new Date(e.start_time);
      const end = e.end_time ? new Date(e.end_time) : new Date(start.getTime() + 3600000);
      const isMerged = e._mergedAccounts && e._mergedAccounts.length > 1;
      return {
        event: e,
        isMerged,
        startMin: start.getHours() * 60 + start.getMinutes(),
        endMin: Math.max(
          end.getHours() * 60 + end.getMinutes(),
          start.getHours() * 60 + start.getMinutes() + 15
        ),
      };
    });

    // Sort by start time, then longer events first, then merged events first
    // so merged events tend to get the leftmost column position
    items.sort((a, b) => {
      if (a.startMin !== b.startMin) return a.startMin - b.startMin;
      const durA = a.endMin - a.startMin;
      const durB = b.endMin - b.startMin;
      if (durB !== durA) return durB - durA;
      // Merged events sort first (true > false, so negate)
      if (a.isMerged !== b.isMerged) return a.isMerged ? -1 : 1;
      return 0;
    });

    // Group overlapping events
    const groups = [];
    let currentGroup = [items[0]];
    let groupEnd = items[0].endMin;

    for (let i = 1; i < items.length; i++) {
      if (items[i].startMin < groupEnd) {
        currentGroup.push(items[i]);
        groupEnd = Math.max(groupEnd, items[i].endMin);
      } else {
        groups.push(currentGroup);
        currentGroup = [items[i]];
        groupEnd = items[i].endMin;
      }
    }
    groups.push(currentGroup);

    // Layout each overlap group
    for (const group of groups) {
      const n = group.length;

      if (n === 1) {
        const pos = computePosition(group[0].event, pxPerHour);
        result.push({
          event: group[0].event,
          top: pos.top,
          height: pos.height,
          left: '1px',
          width: 'calc(100% - 2px)',
          zIndex: 10,
          isBackground: false,
          isMerged: group[0].isMerged,
        });
      } else if (n === 2) {
        for (let i = 0; i < 2; i++) {
          const pos = computePosition(group[i].event, pxPerHour);
          const colWidth = 50;
          const leftPct = i * colWidth;
          result.push({
            event: group[i].event,
            top: pos.top,
            height: pos.height,
            left: `calc(${leftPct}% + 1px)`,
            width: `calc(${colWidth}% - 2px)`,
            zIndex: 10 + i,
            isBackground: false,
            isMerged: group[i].isMerged,
          });
        }
      } else {
        // 3+ events: cascade/fan layout with column assignment
        const columns = [];
        const colAssign = [];
        for (const item of group) {
          let placed = false;
          for (let c = 0; c < columns.length; c++) {
            if (item.startMin >= columns[c]) {
              columns[c] = item.endMin;
              colAssign.push(c);
              placed = true;
              break;
            }
          }
          if (!placed) {
            colAssign.push(columns.length);
            columns.push(item.endMin);
          }
        }

        const step = Math.min(20, 70 / (n - 1));
        for (let i = 0; i < n; i++) {
          const pos = computePosition(group[i].event, pxPerHour);
          const leftPct = colAssign[i] * step;
          result.push({
            event: group[i].event,
            top: pos.top,
            height: pos.height,
            left: `calc(${leftPct}% + 1px)`,
            width: `calc(${100 - leftPct}% - 2px)`,
            zIndex: 10 + colAssign[i],
            isBackground: false,
            isMerged: group[i].isMerged,
          });
        }
      }
    }
  }

  return result;
}

function computePosition(event, pxPerHour) {
  if (!event.start_time) return { top: 0, height: pxPerHour * 0.8 };
  const start = new Date(event.start_time);
  const end = event.end_time ? new Date(event.end_time) : new Date(start.getTime() + 3600000);
  const startMin = start.getHours() * 60 + start.getMinutes();
  const endMin = end.getHours() * 60 + end.getMinutes();
  const duration = Math.max(endMin - startMin, 15);
  return {
    top: (startMin / 60) * pxPerHour,
    height: Math.max((duration / 60) * pxPerHour, pxPerHour * 0.33),
  };
}
