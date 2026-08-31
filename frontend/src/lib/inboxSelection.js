function normalizeScopeValue(value) {
  if (value === null || value === undefined) return '';
  return String(value);
}

function normalizeItemId(value) {
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value) || value < 1) return null;
    return value;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || null;
  }
  return null;
}

function itemKey(value) {
  const normalized = normalizeItemId(value);
  return normalized === null ? null : `${typeof normalized}:${normalized}`;
}

function normalizedItems(values) {
  const items = [];
  const seen = new Set();
  for (const value of values || []) {
    const normalized = normalizeItemId(value);
    const key = itemKey(normalized);
    if (key === null || seen.has(key)) continue;
    seen.add(key);
    items.push({ key, value: normalized });
  }
  return items;
}

/**
 * Session-memory selection for one authoritative Inbox dataset. No browser
 * storage is used, and changing either the authenticated session or dataset
 * clears all selected IDs before the new scope can be used.
 */
export function createInboxSelectionModel(initialScope = {}) {
  let sessionKey = normalizeScopeValue(initialScope.sessionKey);
  let datasetKey = normalizeScopeValue(initialScope.datasetKey);
  let selected = new Map();
  let anchorKey = null;

  function selectedIds() {
    return [...selected.values()];
  }

  function snapshot() {
    return Object.freeze({
      sessionKey,
      datasetKey,
      selectedIds: Object.freeze(selectedIds()),
      size: selected.size,
      anchorId: anchorKey === null ? null : (selected.get(anchorKey) ?? null),
    });
  }

  function clear() {
    selected = new Map();
    anchorKey = null;
    return snapshot();
  }

  function setScope(nextScope = {}) {
    const nextSessionKey = normalizeScopeValue(nextScope.sessionKey);
    const nextDatasetKey = normalizeScopeValue(nextScope.datasetKey);
    const changed = nextSessionKey !== sessionKey || nextDatasetKey !== datasetKey;
    sessionKey = nextSessionKey;
    datasetKey = nextDatasetKey;
    if (changed) clear();
    return changed;
  }

  function isSelected(id) {
    const key = itemKey(id);
    return key !== null && selected.has(key);
  }

  function toggle(id) {
    const value = normalizeItemId(id);
    const key = itemKey(value);
    if (key === null) return snapshot();
    if (selected.has(key)) selected.delete(key);
    else selected.set(key, value);
    anchorKey = key;
    return snapshot();
  }

  function selectRange(id, orderedIds, { replace = false } = {}) {
    const items = normalizedItems(orderedIds);
    const targetKey = itemKey(id);
    const targetIndex = items.findIndex(item => item.key === targetKey);
    if (targetIndex < 0) return snapshot();
    const anchorIndex = items.findIndex(item => item.key === anchorKey);
    if (replace) selected = new Map();
    if (anchorIndex < 0) {
      selected.set(items[targetIndex].key, items[targetIndex].value);
    } else {
      const start = Math.min(anchorIndex, targetIndex);
      const end = Math.max(anchorIndex, targetIndex);
      for (const item of items.slice(start, end + 1)) selected.set(item.key, item.value);
    }
    anchorKey = targetKey;
    return snapshot();
  }

  function selectLoaded(ids, { append = false } = {}) {
    const items = normalizedItems(ids);
    if (!append) selected = new Map();
    for (const item of items) selected.set(item.key, item.value);
    anchorKey = items.at(-1)?.key ?? null;
    return snapshot();
  }

  function prune(authoritativeIds, { authoritative = true } = {}) {
    if (!authoritative) return snapshot();
    const items = normalizedItems(authoritativeIds);
    const available = new Map(items.map(item => [item.key, item.value]));
    const next = new Map();
    for (const key of selected.keys()) {
      if (available.has(key)) next.set(key, available.get(key));
    }
    selected = next;
    if (anchorKey !== null && !selected.has(anchorKey)) anchorKey = null;
    return snapshot();
  }

  return Object.freeze({
    snapshot,
    setScope,
    isSelected,
    toggle,
    selectRange,
    selectLoaded,
    prune,
    clear,
  });
}
