import assert from 'node:assert/strict';
import test from 'node:test';

import {
  availableAtAGlanceDesigns,
  availableAtAGlanceProfiles,
  availableAtAGlanceViews,
  defaultAtAGlanceSelection,
  formatAtAGlanceMoment,
  normalizeAtAGlanceExperience,
  selectAtAGlanceDesign,
  selectAtAGlanceProfile,
  selectAtAGlanceView,
  summarizeAtAGlanceDevice,
} from './atAGlance.js';

const payload = {
  views: [
    { key: 'home', label: 'Home Dashboard', design_keys: ['editorial', 'swiss'], profile_keys: ['landscape_16_9'], default_design: 'editorial' },
    { key: 'day_ahead', label: 'Day Ahead', design_keys: ['editorial'], profile_keys: ['portrait_9_16'], default_design: 'editorial' },
    { key: 'clock', label: 'Clock', design_keys: [], profile_keys: ['landscape_16_9', 'portrait_9_16'] },
  ],
  designs: [
    { key: 'editorial', label: 'Editorial' },
    { key: 'swiss', label: 'Swiss' },
  ],
  display_profiles: [
    { key: 'landscape_16_9', label: 'Landscape 16:9', orientation: 'landscape', aspect_width: 16, aspect_height: 9 },
    { key: 'portrait_9_16', label: 'Portrait 9:16', orientation: 'portrait', aspect_width: 9, aspect_height: 16 },
  ],
  combinations: [
    { key: 'home-editorial-landscape', label: 'Home · Editorial', view: 'home', design: 'editorial', profile: 'landscape_16_9', orientation: 'landscape', aspect_ratio: '16:9' },
    { key: 'home-swiss-landscape', label: 'Home · Swiss', view: 'home', design: 'swiss', profile: 'landscape_16_9', orientation: 'landscape', aspect_ratio: '16:9' },
    { key: 'day-editorial-portrait', label: 'Day Ahead · Editorial', view: 'day_ahead', design: 'editorial', profile: 'portrait_9_16', orientation: 'portrait', aspect_ratio: '9:16' },
    { key: 'clock-landscape', label: 'Clock · Landscape', view: 'clock', design: null, profile: 'landscape_16_9', orientation: 'landscape', aspect_ratio: '16:9' },
    { key: 'clock-portrait', label: 'Clock · Portrait', view: 'clock', design: null, profile: 'portrait_9_16', orientation: 'portrait', aspect_ratio: '9:16' },
  ],
  devices: [],
};

test('normalization keeps only server-declared compatible combinations', () => {
  const experience = normalizeAtAGlanceExperience({
    ...payload,
    combinations: [
      ...payload.combinations,
      { key: 'invalid', label: 'Invalid', view: 'day_ahead', design: 'swiss', profile: 'landscape_16_9' },
    ],
  });

  assert.equal(experience.combinations.length, 5);
  assert.deepEqual(availableAtAGlanceViews(experience).map(view => view.key), ['home', 'day_ahead', 'clock']);
  assert.deepEqual(availableAtAGlanceProfiles(experience, 'day_ahead').map(profile => profile.key), ['portrait_9_16']);
  assert.deepEqual(availableAtAGlanceDesigns(experience, 'home', 'landscape_16_9').map(design => design.key), ['editorial', 'swiss']);
});

test('selection changes stay inside compatible catalog combinations', () => {
  const experience = normalizeAtAGlanceExperience(payload);
  const initial = defaultAtAGlanceSelection(experience, { view: 'home', design: 'editorial' });
  const portrait = selectAtAGlanceView(experience, initial, 'day_ahead');
  const clock = selectAtAGlanceView(experience, portrait, 'clock');
  const landscapeClock = selectAtAGlanceProfile(experience, clock, 'landscape_16_9');
  const unchanged = selectAtAGlanceDesign(experience, landscapeClock, 'swiss');

  assert.equal(initial.key, 'home-editorial-landscape');
  assert.equal(portrait.key, 'day-editorial-portrait');
  assert.equal(landscapeClock.key, 'clock-landscape');
  assert.equal(unchanged.key, 'clock-landscape');
});

test('missing device data becomes a partial error instead of hiding the catalog', () => {
  const experience = normalizeAtAGlanceExperience({ ...payload, devices: undefined });
  assert.equal(experience.combinations.length, 5);
  assert.deepEqual(experience.devices, []);
  assert.match(experience.partial_errors[0], /Terminal status/);
});

test('device summary raises charge attention and predicts the charge moment', () => {
  const summary = summarizeAtAGlanceDevice({
    name: 'Kitchen display',
    hardware_model: 'E1002',
    enrollment_state: 'active',
    last_seen_at: '2026-08-30T11:45:00Z',
    battery_health: {
      status: 'charge_soon',
      current_pct: 18,
      estimated_charge_at: '2026-08-31T14:30:00Z',
      notice: 'Charge this terminal soon.',
    },
  }, new Date('2026-08-30T12:00:00Z'));

  assert.equal(summary.battery, '18% battery');
  assert.equal(summary.tone, 'warning');
  assert.equal(summary.needsAttention, true);
  assert.match(summary.forecast, /Plan to charge by/);
  assert.equal(summary.lastSeen, '15 minutes ago');
  assert.equal(summary.enrollment, 'Secure connection');
});

test('relative check-in formatting handles missing, past, and future values', () => {
  const now = new Date('2026-08-30T12:00:00Z');
  assert.equal(formatAtAGlanceMoment(null, now), 'Not reported yet');
  assert.equal(formatAtAGlanceMoment('2026-08-30T10:00:00Z', now), '2 hours ago');
  assert.equal(formatAtAGlanceMoment('2026-08-31T12:00:00Z', now), 'in 1 day');
});

test('device summary reports learning, stale, and revoked states truthfully', () => {
  const learning = summarizeAtAGlanceDevice({
    enrollment_state: 'pending',
    battery_health: { status: 'healthy', current_pct: 88, sample_count: 1 },
  });
  const stale = summarizeAtAGlanceDevice({
    enrollment_state: 'revoked',
    battery_health: { status: 'stale', current_pct: 70, sample_count: 5 },
  });

  assert.equal(learning.enrollment, 'Secure enrollment pending');
  assert.equal(learning.forecast, 'Learning battery trend · 1 check-in');
  assert.equal(stale.enrollment, 'Access revoked');
  assert.equal(stale.tone, 'warning');
  assert.equal(stale.needsAttention, true);
});
