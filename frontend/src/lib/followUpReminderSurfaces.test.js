import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = relativePath => readFile(new URL(relativePath, import.meta.url), 'utf8');

test('all sending surfaces load account policies behind an authenticated-session guard', async () => {
  const [compose, reader, flow] = await Promise.all([
    read('../pages/Compose.svelte'),
    read('../components/email/EmailView.svelte'),
    read('../pages/Flow.svelte'),
  ]);
  for (const source of [compose, reader, flow]) {
    assert.match(source, /api\.listFollowUpPolicies\(\)/);
    assert.match(source, /normalizeFollowUpPolicyList\(response\)/);
    assert.match(source, /followUpPolicyForAccount/);
  }
  assert.match(compose, /sessionGuard\?\.isCurrent\(\)/);
  assert.match(reader, /sessionIsCurrent\(\)/);
  assert.match(flow, /sessionIsCurrent\(\)/);
});

test('Compose persists and sends exact follow-up mode and timezone fields', async () => {
  const compose = await read('../pages/Compose.svelte');
  assert.match(compose, /function draftSnapshot\(\)[\s\S]*followUpRequestFields/);
  assert.match(compose, /followUpMode = normalizeFollowUpReminderMode\(draft\.follow_up_reminder\)/);
  assert.match(compose, /followUpTimeZone = draft\.follow_up_time_zone/);
  assert.match(compose, /let data = \{[\s\S]*\.\.\.followUpRequestFields/);
  assert.match(compose, /onfollowupchange=\{mode => \{ followUpMode = normalizeFollowUpReminderMode\(mode\); \}\}/);
});

test('Reader and Flow durable replies restore tri-state intent and pass reminder controls to Send', async () => {
  const [reader, flow] = await Promise.all([
    read('../components/email/EmailView.svelte'),
    read('../pages/Flow.svelte'),
  ]);
  for (const source of [reader, flow]) {
    assert.match(source, /followUpMode = normalizeFollowUpReminderMode\(state\.snapshot\?\.follow_up_reminder\)/);
    assert.match(source, /followUpTimeZone = state\.snapshot\?\.follow_up_time_zone/);
    assert.match(source, /followUpReminder: followUp/);
    assert.match(source, /\{followUpAvailable\}/);
    assert.match(source, /\{followUpMode\}/);
    assert.match(source, /\{followUpDefault\}/);
    assert.match(source, /\{followUpSummary\}/);
    assert.match(source, /onfollowupchange=/);
  }
});
