import assert from 'node:assert/strict';
import test from 'node:test';

import {
  insertSnippetText,
  normalizeSnippet,
  normalizeSnippetList,
  normalizeSnippetShortcut,
  rankPersonalSnippets,
  snippetEditorPayload,
  snippetHtmlToPlainText,
  validSnippetShortcut,
} from './personalSnippets.js';


const snippets = [
  {
    snippet_id: '00000000-0000-4000-8000-000000000001',
    name: 'Friendly follow-up',
    shortcut: 'followup',
    body_html: '<p>Just following up on this.</p>',
    body_text: 'Just following up on this.',
    revision: 2,
  },
  {
    snippet_id: '00000000-0000-4000-8000-000000000002',
    name: 'Warm introduction',
    shortcut: 'intro',
    body_html: '<p>I wanted to introduce you both.</p>',
    body_text: 'I wanted to introduce you both.',
    revision: 1,
  },
];


test('normalizes strict user-owned snippet records and rejects duplicate collections', () => {
  assert.equal(normalizeSnippetShortcut(' ;Follow_Up '), 'follow_up');
  assert.equal(validSnippetShortcut('follow_up'), true);
  assert.equal(validSnippetShortcut('bad shortcut'), false);
  assert.equal(normalizeSnippet({ ...snippets[0], revision: 0 }), null);
  assert.equal(normalizeSnippetList({ snippets }).length, 2);
  assert.throws(
    () => normalizeSnippetList({ snippets: [snippets[0], { ...snippets[1], shortcut: 'followup' }] }),
    /duplicates/,
  );
});


test('ranks exact triggers before names and content with deterministic ties', () => {
  assert.equal(rankPersonalSnippets(snippets, ';intro')[0].shortcut, 'intro');
  assert.equal(rankPersonalSnippets(snippets, 'friendly')[0].shortcut, 'followup');
  assert.equal(rankPersonalSnippets(snippets, 'introduce')[0].shortcut, 'intro');
  assert.deepEqual(
    rankPersonalSnippets(snippets).map(item => item.name),
    ['Friendly follow-up', 'Warm introduction'],
  );
});


test('plain inline insertion preserves selected text and restores a trailing caret', () => {
  const result = insertSnippetText('Hello selected world', 'Generated\nreply', 6, 14);
  assert.equal(result.value, 'Hello selected\nGenerated\nreply\n world');
  assert.equal(result.value.slice(6, 14), 'selected');
  assert.equal(result.value.slice(result.caret), ' world');
});


test('editor payloads normalize identity and revisions without inventing content', () => {
  assert.deepEqual(snippetEditorPayload({
    snippetId: snippets[0].snippet_id,
    name: '  Friendly   follow-up ',
    shortcut: ';FollowUp',
    bodyHtml: ' <p>Generated</p> ',
    bodyText: ' Generated\r\nreply ',
    revision: 4,
  }), {
    snippet_id: snippets[0].snippet_id,
    expected_revision: 4,
    name: 'Friendly follow-up',
    shortcut: 'followup',
    body_html: '<p>Generated</p>',
    body_text: 'Generated\nreply',
  });
  assert.equal(snippetHtmlToPlainText('<p>Hello<br>there</p><p>Again</p>'), 'Hello\nthere\nAgain');
});
