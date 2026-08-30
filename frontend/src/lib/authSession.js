let generation = 0;
let userId = null;

export function normalizedAuthenticatedUserId(nextUser) {
  const candidate = nextUser?.id;
  if (Number.isSafeInteger(candidate) && candidate > 0) return String(candidate);
  if (typeof candidate === 'string' && /^[a-zA-Z0-9._-]{1,128}$/.test(candidate)) {
    return candidate;
  }
  return null;
}

export function transitionAuthEpoch(nextUser) {
  const nextUserId = normalizedAuthenticatedUserId(nextUser);
  const changed = nextUserId !== userId;
  if (changed) {
    generation += 1;
    userId = nextUserId;
  }
  return Object.freeze({
    changed,
    snapshot: captureAuthEpoch(),
    user: nextUserId === null ? null : nextUser,
  });
}

export function captureAuthEpoch() {
  return Object.freeze({ generation, userId });
}

export function isAuthEpochCurrent(snapshot) {
  return Boolean(snapshot)
    && snapshot.generation === generation
    && snapshot.userId === userId;
}
