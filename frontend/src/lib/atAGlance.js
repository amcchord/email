function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function cleanKey(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function uniqueKeys(values) {
  return [...new Set(asArray(values).map(cleanKey).filter(Boolean))];
}

function normalizeMessage(value, fallback) {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (value && typeof value === 'object') {
    const message = value.message || value.detail || value.error;
    if (typeof message === 'string' && message.trim()) return message.trim();
  }
  return fallback;
}

function normalizePartialErrors(payload) {
  const errors = [];
  const supplied = payload?.partial_errors ?? payload?.warnings;
  if (Array.isArray(supplied)) {
    supplied.forEach((entry, index) => {
      errors.push(normalizeMessage(entry, `Part of At a Glance is unavailable (${index + 1}).`));
    });
  } else if (supplied && typeof supplied === 'object') {
    Object.entries(supplied).forEach(([section, entry]) => {
      errors.push(normalizeMessage(entry, `${section} is temporarily unavailable.`));
    });
  }
  if (!Array.isArray(payload?.devices)) {
    errors.push('Terminal status is temporarily unavailable.');
  }
  return [...new Set(errors)];
}

export function normalizeAtAGlanceExperience(payload = {}) {
  const designs = asArray(payload.designs).map((design) => ({
    ...design,
    key: cleanKey(design?.key),
    label: cleanKey(design?.label) || cleanKey(design?.key) || 'Design',
  })).filter(design => design.key);
  const designKeys = new Set(designs.map(design => design.key));

  const displayProfiles = asArray(payload.display_profiles).map((profile) => {
    const aspectWidth = Number(profile?.aspect_width);
    const aspectHeight = Number(profile?.aspect_height);
    return {
      ...profile,
      key: cleanKey(profile?.key),
      label: cleanKey(profile?.label) || cleanKey(profile?.key) || 'Display',
      orientation: cleanKey(profile?.orientation) || 'landscape',
      aspect_width: Number.isFinite(aspectWidth) && aspectWidth > 0 ? aspectWidth : 16,
      aspect_height: Number.isFinite(aspectHeight) && aspectHeight > 0 ? aspectHeight : 9,
    };
  }).filter(profile => profile.key);
  const profileKeys = new Set(displayProfiles.map(profile => profile.key));

  const views = asArray(payload.views).map((view) => ({
    ...view,
    key: cleanKey(view?.key),
    label: cleanKey(view?.label) || cleanKey(view?.key) || 'View',
    design_keys: uniqueKeys(view?.design_keys).filter(key => designKeys.has(key)),
    profile_keys: uniqueKeys(view?.profile_keys).filter(key => profileKeys.has(key)),
    default_design: cleanKey(view?.default_design) || null,
  })).filter(view => view.key);
  const viewMap = new Map(views.map(view => [view.key, view]));

  const combinations = asArray(payload.combinations).map((combination) => ({
    ...combination,
    key: cleanKey(combination?.key),
    label: cleanKey(combination?.label) || 'At a Glance preview',
    view: cleanKey(combination?.view),
    design: cleanKey(combination?.design) || null,
    profile: cleanKey(combination?.profile),
    orientation: cleanKey(combination?.orientation),
    aspect_ratio: cleanKey(combination?.aspect_ratio),
  })).filter((combination) => {
    const view = viewMap.get(combination.view);
    if (!view || !profileKeys.has(combination.profile)) return false;
    if (!view.profile_keys.includes(combination.profile)) return false;
    if (combination.design === null) return view.design_keys.length === 0;
    return designKeys.has(combination.design) && view.design_keys.includes(combination.design);
  });

  return {
    views,
    designs,
    display_profiles: displayProfiles,
    combinations,
    devices: asArray(payload.devices).filter(device => device && typeof device === 'object'),
    partial_errors: normalizePartialErrors(payload),
  };
}

function scoreCombination(combination, requested) {
  let score = 0;
  if (requested.view && combination.view === requested.view) score += 8;
  if (requested.profile && combination.profile === requested.profile) score += 4;
  if (Object.hasOwn(requested, 'design') && combination.design === (requested.design || null)) score += 2;
  if (combination.view === 'home') score += 0.5;
  return score;
}

function bestCombination(combinations, requested = {}) {
  return [...combinations].sort((left, right) => (
    scoreCombination(right, requested) - scoreCombination(left, requested)
  ))[0] || null;
}

export function defaultAtAGlanceSelection(experience, preferred = {}) {
  const combinations = asArray(experience?.combinations);
  if (!combinations.length) return null;
  const exact = combinations.find(combination => (
    (!preferred.view || combination.view === preferred.view)
    && (!preferred.profile || combination.profile === preferred.profile)
    && (!Object.hasOwn(preferred, 'design') || combination.design === (preferred.design || null))
  ));
  return exact || bestCombination(combinations, preferred);
}

export function selectAtAGlanceView(experience, current, viewKey) {
  const candidates = asArray(experience?.combinations).filter(item => item.view === viewKey);
  return bestCombination(candidates, current || {}) || current || null;
}

export function selectAtAGlanceProfile(experience, current, profileKey) {
  const candidates = asArray(experience?.combinations).filter(item => (
    item.view === current?.view && item.profile === profileKey
  ));
  return bestCombination(candidates, current || {}) || current || null;
}

export function selectAtAGlanceDesign(experience, current, designKey) {
  const normalizedDesign = designKey || null;
  const exact = asArray(experience?.combinations).find(item => (
    item.view === current?.view
    && item.profile === current?.profile
    && item.design === normalizedDesign
  ));
  return exact || current || null;
}

export function availableAtAGlanceViews(experience) {
  const available = new Set(asArray(experience?.combinations).map(item => item.view));
  return asArray(experience?.views).filter(view => available.has(view.key));
}

export function availableAtAGlanceProfiles(experience, viewKey) {
  const available = new Set(
    asArray(experience?.combinations)
      .filter(item => item.view === viewKey)
      .map(item => item.profile),
  );
  return asArray(experience?.display_profiles).filter(profile => available.has(profile.key));
}

export function availableAtAGlanceDesigns(experience, viewKey, profileKey) {
  const available = new Set(
    asArray(experience?.combinations)
      .filter(item => item.view === viewKey && item.profile === profileKey && item.design)
      .map(item => item.design),
  );
  return asArray(experience?.designs).filter(design => available.has(design.key));
}

export function atAGlanceProfile(experience, profileKey) {
  return asArray(experience?.display_profiles).find(profile => profile.key === profileKey) || null;
}

function validDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatAtAGlanceMoment(value, now = new Date()) {
  const date = validDate(value);
  if (!date) return 'Not reported yet';
  const deltaSeconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const absolute = Math.abs(deltaSeconds);
  if (absolute < 60) return deltaSeconds > 0 ? 'in under a minute' : 'just now';
  const units = absolute < 3600
    ? ['minute', Math.round(absolute / 60)]
    : absolute < 86400
      ? ['hour', Math.round(absolute / 3600)]
      : ['day', Math.round(absolute / 86400)];
  const [unit, count] = units;
  return deltaSeconds > 0
    ? `in ${count} ${unit}${count === 1 ? '' : 's'}`
    : `${count} ${unit}${count === 1 ? '' : 's'} ago`;
}

function formatChargeMoment(value) {
  const date = validDate(value);
  if (!date) return '';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

export function summarizeAtAGlanceDevice(device, now = new Date()) {
  const health = device?.battery_health || {};
  const currentPct = health.current_pct ?? device?.last_battery_pct;
  const currentMv = health.current_mv ?? device?.last_battery_mv;
  const healthStatus = cleanKey(health.status) || 'unknown';
  const chargeAt = formatChargeMoment(health.estimated_charge_at);
  const emptyAt = formatChargeMoment(health.estimated_empty_at);
  const notice = normalizeMessage(health.notice, '');
  const enrollment = cleanKey(device?.enrollment_state) || 'legacy';

  let tone = 'neutral';
  if (healthStatus === 'charge_now') tone = 'danger';
  else if (['charge_soon', 'low', 'warning', 'watch', 'stale'].includes(healthStatus)) tone = 'warning';
  else if (['charging', 'healthy', 'stable', 'good'].includes(healthStatus)) tone = 'success';

  const numericPct = Number(currentPct);
  const numericMv = Number(currentMv);
  let battery = 'Battery not reported';
  if (currentPct != null && Number.isFinite(numericPct)) battery = `${Math.round(numericPct)}% battery`;
  else if (currentMv != null && Number.isFinite(numericMv)) battery = `${Math.round(numericMv)} mV`;

  let forecast = '';
  if (chargeAt) forecast = `Plan to charge by ${chargeAt}`;
  else if (emptyAt) forecast = `Estimated empty ${emptyAt}`;
  else if (Number.isFinite(Number(health.estimated_days_remaining))) {
    const days = Math.max(0, Number(health.estimated_days_remaining));
    forecast = days < 1
      ? `About ${Math.max(1, Math.round(days * 24))} hours remaining`
      : `About ${Math.round(days * 10) / 10} days remaining`;
  } else if (currentPct != null && Number(health.sample_count) < 3 && healthStatus !== 'stale') {
    const samples = Math.max(0, Number(health.sample_count) || 0);
    forecast = `Learning battery trend · ${samples} check-in${samples === 1 ? '' : 's'}`;
  }

  const enrollmentLabels = {
    legacy: 'Legacy connection',
    pending: 'Secure enrollment pending',
    enrolled: 'Secure connection',
    active: 'Secure connection',
    revoked: 'Access revoked',
    review: 'Connection needs review',
  };
  const enrollmentLabel = enrollmentLabels[enrollment] || 'Terminal connection';
  const connectionNeedsAttention = enrollment === 'revoked' || enrollment === 'review';

  return {
    name: cleanKey(device?.name) || 'Unnamed terminal',
    model: cleanKey(device?.hardware_model) || cleanKey(device?.variant) || 'Terminal',
    enrollment: enrollmentLabel,
    lastSeen: formatAtAGlanceMoment(device?.last_seen_at, now),
    battery,
    forecast,
    notice,
    status: healthStatus,
    tone,
    needsAttention: tone === 'danger' || tone === 'warning' || connectionNeedsAttention,
  };
}
