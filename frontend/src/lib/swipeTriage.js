export const SWIPE_TRIAGE_ACTIONS = Object.freeze([
  'archive',
  'snooze',
  'toggle_read',
  'toggle_star',
  'none',
]);

export const SWIPE_TRIAGE_ACTION_DETAILS = Object.freeze({
  archive: Object.freeze({
    label: 'Archive',
    icon: 'archive',
    effect: 'Removes the conversation from Inbox. Undo is available.',
  }),
  snooze: Object.freeze({
    label: 'Snooze',
    icon: 'clock',
    effect: 'Hides the conversation until the time you choose.',
  }),
  toggle_read: Object.freeze({
    label: 'Toggle read',
    icon: 'mail',
    effect: 'Marks unread conversations read, and read conversations unread.',
  }),
  toggle_star: Object.freeze({
    label: 'Toggle star',
    icon: 'star',
    effect: 'Adds or removes the Gmail star.',
  }),
  none: Object.freeze({
    label: 'No action',
    icon: 'minus',
    effect: 'Disables this swipe direction.',
  }),
});

export const DEFAULT_SWIPE_TRIAGE_PREFERENCES = Object.freeze({
  left: 'archive',
  right: 'snooze',
});

const INTERACTIVE_SELECTOR = [
  'a[href]',
  'button',
  'input',
  'select',
  'textarea',
  'summary',
  '[contenteditable="true"]',
  '[role="button"]',
  '[role="link"]',
  '[role="menuitem"]',
  '[data-swipe-ignore]',
].join(',');

function finiteNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function eventCoordinate(event, name) {
  return finiteNumber(event?.[name], 0);
}

function eventMatchesPointer(event, pointerId) {
  return event?.pointerId === pointerId;
}

function isPrimaryTouch(event) {
  return event?.pointerType === 'touch'
    && event?.isPrimary !== false
    && (event?.button === undefined || event.button === 0)
    && !(Number(event?.touches?.length) > 1);
}

export function isInteractiveSwipeTarget(target) {
  if (!target) return false;
  if (typeof target.closest === 'function') {
    return Boolean(target.closest(INTERACTIVE_SELECTOR));
  }
  let current = target;
  while (current) {
    const name = String(current.tagName || '').toLowerCase();
    const role = String(current.role || current.getAttribute?.('role') || '').toLowerCase();
    if (
      ['a', 'button', 'input', 'select', 'textarea', 'summary'].includes(name)
      || ['button', 'link', 'menuitem'].includes(role)
      || current.isContentEditable
      || current.dataset?.swipeIgnore !== undefined
    ) return true;
    current = current.parentElement || current.parentNode;
  }
  return false;
}

export function normalizeSwipeTriagePreferences(value = {}) {
  const normalizeAction = (action, fallback) => (
    SWIPE_TRIAGE_ACTIONS.includes(action) ? action : fallback
  );
  return Object.freeze({
    right: normalizeAction(value?.right, DEFAULT_SWIPE_TRIAGE_PREFERENCES.right),
    left: normalizeAction(value?.left, DEFAULT_SWIPE_TRIAGE_PREFERENCES.left),
  });
}

export function swipeTriageActionForDirection(preferences, direction) {
  const normalized = normalizeSwipeTriagePreferences(preferences);
  if (direction === 'right') return normalized.right;
  if (direction === 'left') return normalized.left;
  return 'none';
}

function idleState(cancelReason = null) {
  return {
    phase: 'idle',
    tracking: false,
    pointerId: null,
    direction: null,
    action: 'none',
    deltaX: 0,
    transformX: 0,
    reveal: 0,
    armed: false,
    cancelReason,
  };
}

/**
 * A DOM-independent, single-pointer swipe recognizer. The caller owns pointer
 * capture and rendering; this controller owns gesture intent and commit safety.
 */
export function createSwipeTriageController(options = {}) {
  const threshold = Math.max(24, finiteNumber(options.threshold, 72));
  const intentDistance = Math.max(4, finiteNumber(options.intentDistance, 10));
  const axisDominance = Math.max(1.05, finiteNumber(options.axisDominance, 1.35));
  const maxTranslation = Math.max(threshold, finiteNumber(options.maxTranslation, threshold * 1.35));
  const onCommit = typeof options.onCommit === 'function' ? options.onCommit : null;
  const getDisabled = typeof options.getDisabled === 'function' ? options.getDisabled : null;
  const getGeneration = typeof options.getGeneration === 'function' ? options.getGeneration : null;

  let context = {
    disabled: Boolean(options.disabled),
    generation: options.generation ?? null,
    preferences: normalizeSwipeTriagePreferences(options.preferences),
  };
  let state = idleState();
  let active = null;

  function currentDisabled() {
    return getDisabled ? Boolean(getDisabled()) : context.disabled;
  }

  function currentGeneration() {
    return getGeneration ? getGeneration() : context.generation;
  }

  function snapshot() {
    return Object.freeze({ ...state });
  }

  function reset(cancelReason = null) {
    active = null;
    state = idleState(cancelReason);
    return snapshot();
  }

  function cancel(reason = 'cancelled') {
    if (!active) return snapshot();
    return reset(reason);
  }

  function isContextCurrent() {
    if (!active) return false;
    if (currentDisabled()) {
      cancel('disabled');
      return false;
    }
    if (!Object.is(currentGeneration(), active.generation)) {
      cancel('generation-changed');
      return false;
    }
    return true;
  }

  function updateContext(changes = {}) {
    const previousGeneration = context.generation;
    const previousDisabled = context.disabled;
    context = {
      disabled: changes.disabled === undefined ? context.disabled : Boolean(changes.disabled),
      generation: changes.generation === undefined ? context.generation : changes.generation,
      preferences: changes.preferences === undefined
        ? context.preferences
        : normalizeSwipeTriagePreferences(changes.preferences),
    };
    if (
      active
      && (
        (!previousDisabled && context.disabled)
        || !Object.is(previousGeneration, context.generation)
      )
    ) cancel(context.disabled ? 'disabled' : 'generation-changed');
    return snapshot();
  }

  function pointerDown(event) {
    if (active) {
      if (event?.pointerType === 'touch' && !eventMatchesPointer(event, active.pointerId)) {
        cancel('multi-touch');
      }
      return false;
    }
    if (
      currentDisabled()
      || !isPrimaryTouch(event)
      || isInteractiveSwipeTarget(event?.target)
    ) return false;
    const pointerId = event?.pointerId;
    if (pointerId === undefined || pointerId === null) return false;
    active = {
      pointerId,
      startX: eventCoordinate(event, 'clientX'),
      startY: eventCoordinate(event, 'clientY'),
      generation: currentGeneration(),
      preferences: context.preferences,
      committed: false,
    };
    state = {
      ...idleState(),
      phase: 'pending',
      tracking: true,
      pointerId,
    };
    return true;
  }

  function pointerMove(event) {
    if (!active || !eventMatchesPointer(event, active.pointerId) || !isContextCurrent()) {
      return snapshot();
    }
    const deltaX = eventCoordinate(event, 'clientX') - active.startX;
    const deltaY = eventCoordinate(event, 'clientY') - active.startY;
    const absX = Math.abs(deltaX);
    const absY = Math.abs(deltaY);

    if (state.phase === 'pending') {
      if (Math.max(absX, absY) < intentDistance) return snapshot();
      if (absY >= intentDistance && absY > absX) return cancel('vertical-scroll');
      if (absX < intentDistance || absX < absY * axisDominance) return snapshot();
    }

    event?.preventDefault?.();
    const direction = deltaX >= 0 ? 'right' : 'left';
    const action = swipeTriageActionForDirection(active.preferences, direction);
    const restrained = absX <= maxTranslation
      ? absX
      : maxTranslation + ((absX - maxTranslation) * 0.15);
    const transformX = Math.sign(deltaX) * restrained;
    state = {
      phase: 'swiping',
      tracking: true,
      pointerId: active.pointerId,
      direction,
      action,
      deltaX,
      transformX,
      reveal: Math.min(1, Math.abs(transformX) / threshold),
      armed: action !== 'none' && absX >= threshold,
      cancelReason: null,
    };
    return snapshot();
  }

  function pointerUp(event) {
    if (!active || !eventMatchesPointer(event, active.pointerId) || !isContextCurrent()) {
      return null;
    }
    const shouldCommit = state.phase === 'swiping' && state.armed && !active.committed;
    if (!shouldCommit) {
      reset('below-threshold');
      return null;
    }
    active.committed = true;
    const commit = Object.freeze({
      action: state.action,
      direction: state.direction,
      pointerId: active.pointerId,
      deltaX: state.deltaX,
    });
    reset();
    onCommit?.(commit);
    return commit;
  }

  function pointerCancel(event) {
    if (active && eventMatchesPointer(event, active.pointerId)) cancel('pointer-cancel');
    return snapshot();
  }

  function lostPointerCapture(event) {
    if (active && eventMatchesPointer(event, active.pointerId)) cancel('lost-pointer-capture');
    return snapshot();
  }

  return Object.freeze({
    getState: snapshot,
    updateContext,
    pointerDown,
    pointerMove,
    pointerUp,
    pointerCancel,
    lostPointerCapture,
    cancel,
  });
}
