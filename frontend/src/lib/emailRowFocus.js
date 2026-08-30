export function shouldFocusAdjacentRow({
  previousSelectedId,
  selectedId,
  previousEmailIds,
  emailIds,
}) {
  if (previousSelectedId == null || selectedId == null) return false;
  if (previousSelectedId === selectedId) return false;

  const previousIds = previousEmailIds instanceof Set
    ? previousEmailIds
    : new Set(previousEmailIds || []);
  const currentIds = emailIds instanceof Set ? emailIds : new Set(emailIds || []);

  return previousIds.has(previousSelectedId)
    && !currentIds.has(previousSelectedId)
    && currentIds.has(selectedId);
}

export function focusEmailRow(container, emailId) {
  if (!container || emailId == null) return false;
  const targetId = String(emailId);
  const row = Array.from(container.querySelectorAll('[data-email-row-id]'))
    .find(candidate => candidate.dataset.emailRowId === targetId);

  if (!row || row.getClientRects().length === 0) return false;
  row.focus();
  return true;
}

export function focusEmailRowOrFallback(container, emailId, fallback = container) {
  if (focusEmailRow(container, emailId)) return 'row';
  if (fallback?.focus) {
    fallback.focus();
    return 'fallback';
  }
  return false;
}
