import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const [compose, apiClient] = await Promise.all([
  readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8'),
  readFile(new URL('./api.js', import.meta.url), 'utf8'),
]);


test('Compose persists and sends only committed recipient arrays', () => {
  assert.match(compose, /let toRecipients = \$state\(\[\]\)/);
  assert.match(compose, /let ccRecipients = \$state\(\[\]\)/);
  assert.match(compose, /let bccRecipients = \$state\(\[\]\)/);
  assert.match(compose, /toRecipientPending \|\| ccRecipientPending \|\| bccRecipientPending/);
  assert.match(compose, /function draftSnapshot\(\) \{[\s\S]*to: \[\.\.\.toRecipients\],[\s\S]*cc: \[\.\.\.ccRecipients\],[\s\S]*bcc: \[\.\.\.bccRecipients\]/);
  assert.match(compose, /let data = \{[\s\S]*to: \[\.\.\.toRecipients\],[\s\S]*cc: \[\.\.\.ccRecipients\],[\s\S]*bcc: \[\.\.\.bccRecipients\]/);
  assert.doesNotMatch(compose, /function parseRecipients/);
  assert.doesNotMatch(compose, /bind:value=\{to\}|bind:value=\{cc\}|bind:value=\{bcc\}/);
});


test('all three recipient fields share account-scoped suggestions and cross-field duplicate state', () => {
  assert.equal((compose.match(/<RecipientField/g) || []).length, 3);
  assert.match(compose, /field="to"[\s\S]*bind:recipients=\{toRecipients\}[\s\S]*recipientCollections=\{\[ccRecipients, bccRecipients\]\}/);
  assert.match(compose, /field="cc"[\s\S]*bind:recipients=\{ccRecipients\}[\s\S]*recipientCollections=\{\[toRecipients, bccRecipients\]\}/);
  assert.match(compose, /field="bcc"[\s\S]*bind:recipients=\{bccRecipients\}[\s\S]*recipientCollections=\{\[toRecipients, ccRecipients\]\}/);
  assert.equal((compose.match(/accountKey=\{selectedAccountId\}/g) || []).length, 3);
  assert.equal((compose.match(/loadSuggestions=\{loadRecipientSuggestions\}/g) || []).length, 3);
  assert.equal((compose.match(/bind:pending=\{/g) || []).length, 3);
  assert.match(compose, /!sessionGuard\?\.isCurrent\(\)[\s\S]*accountId !== Number\(selectedAccountId\)/);
  assert.match(compose, /function recipientPendingMessage\(\) \{[\s\S]*Finish or remove the incomplete recipient/);
  assert.match(compose, /if \(recipientEntryPending\) \{[\s\S]*showToast\(recipientPendingMessage\(\), 'error'\)/);
  assert.match(compose, /disabled=\{!writingSurfaceReady \|\| !draftState\.canSend \|\| recipientEntryPending\}/);
});


test('the API client forwards an abortable, encoded, bounded recipient lookup', () => {
  assert.match(apiClient, /listComposeRecipients: \(\{ accountId, query, limit = 8, signal \} = \{\}\)/);
  assert.match(apiClient, /account_id: String\(accountId\)/);
  assert.match(apiClient, /q: String\(query \|\| ''\)/);
  assert.match(apiClient, /request\('GET', `\/compose\/recipients\?\$\{params\.toString\(\)\}`, null, \{ signal \}\)/);
});
