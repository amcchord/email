export function claimLabelPickerKeyEvent(event, { preventEscape = false } = {}) {
  event?.stopPropagation?.();
  if (preventEscape && event?.key === 'Escape') event.preventDefault?.();
  return event?.key || '';
}
