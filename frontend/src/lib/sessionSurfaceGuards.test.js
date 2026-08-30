import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('standalone email viewer remounts and suppresses old identity completions', async () => {
  const [app, standalone] = await Promise.all([
    source('../App.svelte'),
    source('../pages/EmailViewStandalone.svelte'),
  ]);

  assert.match(
    app,
    /standaloneEmailId !== null[\s\S]*\{#if \$user\}[\s\S]*\{#key \$authenticatedSessionGeneration\}[\s\S]*<LazyRouteState/,
  );
  assert.match(standalone, /sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(
    standalone,
    /const result = await api\.getEmail\(id\);\s*if \(!standaloneSessionIsCurrent\(\) \|\| requestGeneration !== loadGeneration\) return false;/,
  );
  assert.match(
    standalone,
    /await api\.emailActions\(emailIds, action\);\s*if \(!standaloneSessionIsCurrent\(\)\) return false;/,
  );
  assert.match(standalone, /sessionGuard\.dispose\(\);\s*document\.title = 'Mail';/);
});

test('device authorization remounts and cannot complete for the next identity', async () => {
  const [app, deviceAuth] = await Promise.all([
    source('../App.svelte'),
    source('../pages/DeviceAuth.svelte'),
  ]);

  assert.match(
    app,
    /deviceAuthCode !== null[\s\S]*\{#key \$authenticatedSessionGeneration\}[\s\S]*<DeviceAuth/,
  );
  assert.match(deviceAuth, /sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(
    deviceAuth,
    /await api\.deviceAuthorize\(userCode\.trim\(\)\.toUpperCase\(\)\);\s*if \(!deviceSessionIsCurrent\(\)\) return false;\s*status = 'success';/,
  );
  assert.match(
    deviceAuth,
    /await tick\(\);\s*if \(!deviceSessionIsCurrent\(\)\) return;\s*void authorize\(\);/,
  );
});

test('secondary authenticated surfaces gate post-await state and toast writes', async () => {
  const [mailActions, stats, calendar] = await Promise.all([
    source('../components/email/MailActionStatus.svelte'),
    source('../pages/Stats.svelte'),
    source('../pages/Calendar.svelte'),
  ]);

  assert.match(mailActions, /sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(
    mailActions,
    /await api\.retryMailAction\(operation\.request_id\);\s*if \(!mailActionSessionIsCurrent\(\)\) return;/,
  );
  assert.match(stats, /sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(
    stats,
    /const result = await api\.getStats\([\s\S]*if \(!statsSessionIsCurrent\(\) \|\| requestGeneration !== loadGeneration\) return false;/,
  );
  assert.match(calendar, /sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(
    calendar,
    /const result = await api\.reauthorizeAccount\(accountId, \{ returnPage: 'calendar' \}\);\s*if \(!calendarSessionIsCurrent\(\)\) return;/,
  );
  assert.match(
    calendar,
    /await api\.triggerCalendarSync\(selectedAccountSnapshot \|\| undefined\);\s*if \(!calendarSessionIsCurrent\(\)\) return;/,
  );
});
