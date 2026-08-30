import assert from 'node:assert/strict';
import test from 'node:test';

import {
  EMAIL_SEARCH_LIMITS,
  EMAIL_SEARCH_OPERATORS,
  SEARCH_OPERATORS,
  EmailSearchParseError,
  analyzeEmailSearch,
  getEmailSearchChips,
  getEmailSearchScopeLabel,
  getEmailSearchSuggestions,
  parseEmailSearch,
  removeEmailSearchClause,
  removeSearchClause,
  searchSuggestions,
  serializeEmailSearch,
} from './emailSearch.js';

test('whitespace is implicit AND and standalone OR creates stable groups', () => {
  const parsed = parseEmailSearch('from:alice subject:"Quarterly report" or -has:attachment');

  assert.equal(parsed.groups.length, 2);
  assert.deepEqual(parsed.groups.map(group => group.map(clause => clause.id)), [
    ['clause-0', 'clause-1'],
    ['clause-2'],
  ]);
  assert.deepEqual(parsed.clauses.map(clause => ({
    type: clause.type,
    operator: clause.operator,
    value: clause.value,
    negated: clause.negated,
    quoted: clause.quoted,
  })), [
    { type: 'operator', operator: 'from', value: 'alice', negated: false, quoted: false },
    { type: 'operator', operator: 'subject', value: 'Quarterly report', negated: false, quoted: true },
    { type: 'operator', operator: 'has', value: 'attachment', negated: true, quoted: false },
  ]);
  assert.equal(parsed.normalizedQuery, 'from:alice subject:"Quarterly report" OR -has:attachment');
  assert.equal(parsed.tokens.filter(token => token.type === 'or').length, 1);
});

test('operators and their enumerated values are case-insensitive', () => {
  const parsed = parseEmailSearch('FROM:Austin@Example.com IS:UNREAD In:Drafts');

  assert.deepEqual(parsed.clauses.map(clause => clause.operator), ['from', 'is', 'in']);
  assert.deepEqual(parsed.clauses.map(clause => clause.normalizedValue), [
    'austin@example.com',
    'unread',
    'drafts',
  ]);
  assert.equal(parsed.clauses[0].value, 'Austin@Example.com');
});

test('unknown operator-shaped input remains ordinary text', () => {
  const parsed = parseEmailSearch('foo:bar AND:anything');

  assert.deepEqual(parsed.clauses.map(clause => ({ type: clause.type, value: clause.value })), [
    { type: 'text', value: 'foo:bar' },
    { type: 'text', value: 'AND:anything' },
  ]);
});

test('text and operands preserve plus, at-sign, ampersand, and Unicode', () => {
  const parsed = parseEmailSearch('-José+工作@example.com label:R&D café');

  assert.equal(parsed.clauses[0].value, 'José+工作@example.com');
  assert.equal(parsed.clauses[0].negated, true);
  assert.equal(parsed.clauses[1].value, 'R&D');
  assert.equal(parsed.clauses[2].value, 'café');
});

test('quoted phrases and operator values decode only supported escapes', () => {
  const parsed = parseEmailSearch('"exact \\"phrase\\"" from:"Austin \\\\ Team"');

  assert.equal(parsed.clauses[0].value, 'exact "phrase"');
  assert.equal(parsed.clauses[1].value, 'Austin \\ Team');
  assert.equal(
    serializeEmailSearch(parsed),
    '"exact \\"phrase\\"" from:"Austin \\\\ Team"',
  );
});

test('valid calendar dates include leap days and reject impossible dates', () => {
  assert.doesNotThrow(() => parseEmailSearch('after:2024-02-29 before:2026-12-31'));

  for (const query of ['after:2023-02-29', 'before:2026-04-31', 'after:2026-2-01', 'after:0000-01-01']) {
    const result = analyzeEmailSearch(query);
    assert.equal(result.valid, false, query);
    assert.equal(result.error.code, 'INVALID_DATE', query);
  }
});

test('recognized enumerated operators reject unsupported values', () => {
  const cases = [
    ['is:important', /read, unread, starred/],
    ['has:calendar', /attachment, attachments/],
    ['in:outbox', /inbox, sent, drafts/],
  ];

  for (const [query, message] of cases) {
    const result = analyzeEmailSearch(query);
    assert.equal(result.valid, false);
    assert.equal(result.error.code, 'INVALID_VALUE');
    assert.match(result.error.message, message);
  }
});

test('OR must have one clause on each side', () => {
  const cases = [
    ['OR from:a', 'LEADING_OR', 'OR cannot appear at the beginning of a search.'],
    ['from:a OR', 'TRAILING_OR', 'OR cannot appear at the end of a search.'],
    ['from:a OR or to:b', 'CONSECUTIVE_OR', 'OR must have a search term on both sides.'],
  ];

  for (const [query, code, message] of cases) {
    const result = analyzeEmailSearch(query);
    assert.equal(result.valid, false, query);
    assert.deepEqual(result.error, {
      code,
      message,
      index: query.toLowerCase().lastIndexOf('or'),
      length: 2,
    });
  }

  assert.equal(parseEmailSearch('ORANGE orca from:or').groups[0].length, 3);
  assert.equal(parseEmailSearch('"OR"').clauses[0].value, 'OR');
});

test('invalid quotes, escapes, parentheses, and negation produce stable errors', () => {
  const cases = [
    ['"unfinished', 'UNCLOSED_QUOTE', 'Close the quoted search term with a double quote.'],
    ['"dangling\\', 'DANGLING_ESCAPE', 'A backslash at the end of a search term is incomplete.'],
    ['dangling\\', 'DANGLING_ESCAPE', 'A backslash at the end of a search term is incomplete.'],
    ['"bad\\n"', 'INVALID_ESCAPE', 'Only \\" and \\\\ escapes are allowed inside quotes.'],
    ['subject:foo(bar)', 'UNQUOTED_PARENTHESIS', 'Parentheses must be inside quotes.'],
    ['foo"bar"', 'UNEXPECTED_QUOTE', 'Quotes must wrap an entire search term or operator value.'],
    ['--from:a', 'MULTIPLE_NEGATION', 'Use only one leading "-" to exclude a search term.'],
    ['- from:a', 'EMPTY_NEGATION', 'Add a search term after "-".'],
  ];

  for (const [query, code, message] of cases) {
    const result = analyzeEmailSearch(query);
    assert.equal(result.valid, false, query);
    assert.equal(result.error.code, code, query);
    assert.equal(result.error.message, message, query);
    assert.equal(result.errors.length, 1);
  }
});

test('recognized operators require non-empty operands, including empty quotes', () => {
  for (const query of ['from:', 'subject: ', 'body:""']) {
    const result = analyzeEmailSearch(query);
    assert.equal(result.valid, false, query);
    assert.equal(result.error.code, 'EMPTY_OPERAND', query);
    assert.match(result.error.message, /Add a value after/);
  }
});

test('query, clause, and operand limits are enforced at their boundaries', () => {
  const boundaryQuery = `${'x'.repeat(EMAIL_SEARCH_LIMITS.operandLength)} ${'y'.repeat(EMAIL_SEARCH_LIMITS.operandLength - 1)}`;
  assert.equal(boundaryQuery.length, EMAIL_SEARCH_LIMITS.queryLength);
  assert.doesNotThrow(() => parseEmailSearch(boundaryQuery));
  assert.equal(
    analyzeEmailSearch('x'.repeat(EMAIL_SEARCH_LIMITS.queryLength + 1)).error.code,
    'QUERY_TOO_LONG',
  );

  assert.doesNotThrow(() => parseEmailSearch(`subject:${'x'.repeat(EMAIL_SEARCH_LIMITS.operandLength)}`));
  assert.doesNotThrow(() => parseEmailSearch(`subject:${'😀'.repeat(EMAIL_SEARCH_LIMITS.operandLength)}`));
  assert.equal(
    analyzeEmailSearch(`subject:${'x'.repeat(EMAIL_SEARCH_LIMITS.operandLength + 1)}`).error.code,
    'OPERAND_TOO_LONG',
  );

  assert.doesNotThrow(() => parseEmailSearch(Array(EMAIL_SEARCH_LIMITS.clauses).fill('x').join(' ')));
  assert.equal(
    analyzeEmailSearch(Array(EMAIL_SEARCH_LIMITS.clauses + 1).fill('x').join(' ')).error.code,
    'TOO_MANY_CLAUSES',
  );
});

test('analysis never throws and returns UI-ready success and error shapes', () => {
  const valid = analyzeEmailSearch('from:a');
  assert.equal(valid.valid, true);
  assert.equal(valid.error, null);
  assert.deepEqual(valid.errors, []);
  assert.equal(valid.parsed, valid.ast);
  assert.equal(valid.chips[0].label, 'From: a');

  const invalid = analyzeEmailSearch({ toString() { throw new Error('generated conversion failure'); } });
  assert.equal(invalid.valid, false);
  assert.equal(invalid.error.code, 'INVALID_INPUT');
  assert.equal(invalid.parsed, null);
  assert.deepEqual(invalid.groups, []);

  assert.throws(
    () => parseEmailSearch('from:'),
    error => error instanceof EmailSearchParseError && error.code === 'EMPTY_OPERAND',
  );
});

test('operator metadata and contextual suggestions are deterministic', () => {
  assert.equal(SEARCH_OPERATORS, EMAIL_SEARCH_OPERATORS);
  assert.deepEqual(EMAIL_SEARCH_OPERATORS.map(item => item.operator), [
    'from', 'to', 'cc', 'bcc', 'subject', 'body', 'after', 'before', 'is', 'has', 'in', 'account', 'label',
  ]);
  assert.deepEqual(
    getEmailSearchSuggestions('su').map(item => item.syntax),
    ['subject:'],
  );
  assert.deepEqual(
    getEmailSearchSuggestions('from:a is:un').map(item => item.insertText),
    ['is:unread', 'is:unstarred'],
  );
  assert.deepEqual(
    getEmailSearchSuggestions('has:attach').map(item => item.value),
    ['attachment', 'attachments'],
  );
  assert.equal(getEmailSearchSuggestions('foo:').length, 0);
  assert.equal(getEmailSearchSuggestions('"quoted').length, 0);
  assert.deepEqual(searchSuggestions('su'), getEmailSearchSuggestions('su'));
});

test('chips expose readable labels, canonical tokens, and AND/OR joins', () => {
  const chips = getEmailSearchChips('-from:"Austin M" unread OR in:archive');

  assert.deepEqual(chips.map(chip => ({ label: chip.label, token: chip.token, join: chip.join })), [
    { label: 'Not From: Austin M', token: '-from:"Austin M"', join: null },
    { label: 'unread', token: 'unread', join: 'and' },
    { label: 'In: archive', token: 'in:archive', join: 'or' },
  ]);
});

test('scope labels describe regular, protected, and mixed-folder results truthfully', () => {
  assert.equal(getEmailSearchScopeLabel('from:a'), 'All regular mail');
  assert.equal(getEmailSearchScopeLabel('in:trash'), 'Trash results');
  assert.equal(getEmailSearchScopeLabel('in:spam'), 'Spam results');
  assert.equal(getEmailSearchScopeLabel('in:anywhere'), 'All mail, including spam and trash');
  assert.equal(
    getEmailSearchScopeLabel('in:trash OR from:a'),
    'Matching mail across selected folders',
  );
});

test('removing clauses reserializes AND terms and collapses empty OR groups', () => {
  const parsed = parseEmailSearch('from:a subject:"Road map" OR -has:attachment account:work');

  assert.equal(
    removeEmailSearchClause(parsed, parsed.clauses[1]),
    'from:a OR -has:attachment account:work',
  );
  assert.equal(
    removeEmailSearchClause(parsed, 'clause-2'),
    'from:a subject:"Road map" OR account:work',
  );
  assert.equal(removeEmailSearchClause('from:a OR to:b', 0), 'to:b');
  assert.equal(removeEmailSearchClause('from:a', 0), '');
  assert.equal(removeSearchClause('from:a OR to:b', 1), 'from:a');
  assert.equal(removeEmailSearchClause(parsed, 'missing'), parsed.normalizedQuery);
});
