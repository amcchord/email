import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clampInlineSnippetMenuPosition,
  detectInlineSnippetTrigger,
  findInlineSnippetTrigger,
  replaceInlineSnippetRange,
  replaceInlineSnippetText,
} from './inlineSnippetExpansion.js';


test('safe boundaries detect an empty or ASCII shortcut at a collapsed caret', () => {
  assert.deepEqual(detectInlineSnippetTrigger(';', {
    selectionStart: 1,
    selectionEnd: 1,
  }), {
    start: 0,
    end: 1,
    raw: ';',
    query: '',
    normalizedQuery: '',
  });
  assert.deepEqual(detectInlineSnippetTrigger('Hello ;Follow_UP-2', {
    selectionStart: 18,
  }), {
    start: 6,
    end: 18,
    raw: ';Follow_UP-2',
    query: 'Follow_UP-2',
    normalizedQuery: 'follow_up-2',
  });
  assert.equal(detectInlineSnippetTrigger('First\n;second', {
    selectionStart: 13,
  })?.query, 'second');
  assert.equal(detectInlineSnippetTrigger('x;block', {
    selectionStart: 7,
    blockStart: 1,
  })?.start, 1);
});


test('editor-facing trigger and replacement forms preserve exact document coordinates', () => {
  const trigger = findInlineSnippetTrigger('Hello ;follow', 13);
  assert.deepEqual(trigger, {
    from: 6,
    to: 13,
    token: ';follow',
    query: 'follow',
    normalizedQuery: 'follow',
  });
  assert.deepEqual(replaceInlineSnippetText('Hello ;follow', trigger, 'Thanks'), {
    value: 'Hello Thanks',
    inserted: 'Thanks',
    caret: 12,
    from: 6,
    to: 13,
  });
  assert.equal(replaceInlineSnippetText('Hello ;changed', trigger, 'Thanks'), null);
});


test('unsafe boundaries, grammar, ranges, and selections fail closed', () => {
  const rejected = [
    ['word;sig', 8],
    ['(;sig', 5],
    [' ;-bad', 6],
    [' ;has.dot', 9],
    [' ;café', 6],
    [` ;${'a'.repeat(33)}`, 35],
  ];
  for (const [value, caret] of rejected) {
    assert.equal(detectInlineSnippetTrigger(value, { selectionStart: caret }), null, value);
  }
  assert.equal(detectInlineSnippetTrigger(' ;sig', {
    selectionStart: 1,
    selectionEnd: 5,
  }), null);
  assert.equal(detectInlineSnippetTrigger(' ;sig', {
    selectionStart: 5,
    blockStart: 6,
  }), null);
});


test('replacement changes only the exact captured range and collapses after inserted text', () => {
  const source = 'Hello ;follow world';
  const trigger = detectInlineSnippetTrigger(source, { selectionStart: 13 });
  assert.deepEqual(replaceInlineSnippetRange(source, trigger, 'Thanks,\nAda'), {
    value: 'Hello Thanks,\nAda world',
    selectionStart: 17,
    selectionEnd: 17,
    replaced: { start: 6, end: 13 },
  });
  assert.equal(replaceInlineSnippetRange('Hello ;changed world', trigger, 'No'), null);
  assert.equal(replaceInlineSnippetRange(source, { start: -1, end: 3, raw: ';x' }, 'No'), null);
  assert.equal(replaceInlineSnippetRange(source, { start: 6, end: 13, raw: 'follow' }, 'No'), null);
});


test('menu placement clamps to narrow viewports and flips above a low caret', () => {
  assert.deepEqual(clampInlineSnippetMenuPosition({
    left: 360,
    top: 80,
    bottom: 100,
  }, {
    width: 390,
    height: 844,
  }), {
    left: 8,
    top: 106,
    width: 374,
    maxHeight: 320,
    placement: 'below',
  });

  assert.deepEqual(clampInlineSnippetMenuPosition({
    left: -50,
    top: 580,
    bottom: 600,
  }, {
    width: 800,
    height: 640,
  }), {
    left: 8,
    top: 254,
    width: 384,
    maxHeight: 320,
    placement: 'above',
  });
});
