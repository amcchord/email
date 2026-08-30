/**
 * Pure parser and presentation helpers for the email search box.
 *
 * Whitespace joins clauses with AND. Standalone OR tokens split the query into
 * groups, so callers can translate `groups` directly to (AND...) OR (AND...).
 */

export const EMAIL_SEARCH_LIMITS = Object.freeze({
  queryLength: 512,
  clauses: 32,
  operandLength: 256,
});

const OPERATOR_DEFINITIONS = [
  ['from', 'From', 'Messages from a sender'],
  ['to', 'To', 'Messages sent to a recipient'],
  ['cc', 'Cc', 'Messages copied to a recipient'],
  ['bcc', 'Bcc', 'Messages blind-copied to a recipient'],
  ['subject', 'Subject', 'Text in the subject line'],
  ['body', 'Body', 'Text in the message body'],
  ['after', 'After', 'Messages after a date (YYYY-MM-DD)'],
  ['before', 'Before', 'Messages before a date (YYYY-MM-DD)'],
  ['is', 'Is', 'Messages with a status'],
  ['has', 'Has', 'Messages with a feature'],
  ['in', 'In', 'Messages in a mailbox'],
  ['account', 'Account', 'Messages in an account'],
  ['label', 'Label', 'Messages with a label'],
];

const VALUE_DEFINITIONS = Object.freeze({
  is: Object.freeze(['read', 'unread', 'starred', 'unstarred', 'draft', 'sent']),
  has: Object.freeze(['attachment', 'attachments']),
  in: Object.freeze(['inbox', 'sent', 'drafts', 'archive', 'starred', 'spam', 'trash', 'all', 'anywhere']),
});

export const EMAIL_SEARCH_OPERATORS = Object.freeze(
  OPERATOR_DEFINITIONS.map(([operator, label, description]) => Object.freeze({
    operator,
    label,
    syntax: `${operator}:`,
    insertText: `${operator}:`,
    description,
    values: VALUE_DEFINITIONS[operator] || null,
  })),
);

export const EMAIL_SEARCH_SUGGESTIONS = EMAIL_SEARCH_OPERATORS;
export const SEARCH_OPERATOR_SUGGESTIONS = EMAIL_SEARCH_OPERATORS;
export const SEARCH_OPERATORS = EMAIL_SEARCH_OPERATORS;

const OPERATOR_BY_NAME = new Map(
  EMAIL_SEARCH_OPERATORS.map(definition => [definition.operator, definition]),
);

function characterLength(value) {
  return Array.from(value).length;
}

const ERROR_MESSAGES = Object.freeze({
  QUERY_TOO_LONG: `Search query cannot exceed ${EMAIL_SEARCH_LIMITS.queryLength} characters.`,
  TOO_MANY_CLAUSES: `Search query cannot contain more than ${EMAIL_SEARCH_LIMITS.clauses} clauses.`,
  OPERAND_TOO_LONG: `Search terms cannot exceed ${EMAIL_SEARCH_LIMITS.operandLength} characters.`,
  LEADING_OR: 'OR cannot appear at the beginning of a search.',
  TRAILING_OR: 'OR cannot appear at the end of a search.',
  CONSECUTIVE_OR: 'OR must have a search term on both sides.',
  MULTIPLE_NEGATION: 'Use only one leading "-" to exclude a search term.',
  EMPTY_NEGATION: 'Add a search term after "-".',
  UNCLOSED_QUOTE: 'Close the quoted search term with a double quote.',
  DANGLING_ESCAPE: 'A backslash at the end of a search term is incomplete.',
  INVALID_ESCAPE: 'Only \\" and \\\\ escapes are allowed inside quotes.',
  UNQUOTED_PARENTHESIS: 'Parentheses must be inside quotes.',
  UNEXPECTED_QUOTE: 'Quotes must wrap an entire search term or operator value.',
  MISSING_SEPARATOR: 'Add a space between search terms.',
  EMPTY_TERM: 'Add text inside the quoted search term.',
  INVALID_INPUT: 'Search query could not be read.',
});

export class EmailSearchParseError extends SyntaxError {
  constructor(code, message, index = 0, length = 1) {
    super(message || ERROR_MESSAGES[code] || 'Invalid search query.');
    this.name = 'EmailSearchParseError';
    this.code = code;
    this.index = Math.max(0, Number.isFinite(index) ? index : 0);
    this.length = Math.max(0, Number.isFinite(length) ? length : 1);
  }

  toJSON() {
    return {
      code: this.code,
      message: this.message,
      index: this.index,
      length: this.length,
    };
  }
}

function fail(code, index, message, length = 1) {
  throw new EmailSearchParseError(code, message, index, length);
}

function isWhitespace(character) {
  return character != null && /\s/u.test(character);
}

function isStandaloneOr(source, index) {
  return source.slice(index, index + 2).toLowerCase() === 'or'
    && (index + 2 === source.length || isWhitespace(source[index + 2]));
}

function readQuoted(source, quoteIndex) {
  let value = '';
  let index = quoteIndex + 1;

  while (index < source.length) {
    const character = source[index];
    if (character === '"') {
      return { value, end: index + 1 };
    }

    if (character === '\\') {
      if (index + 1 >= source.length) {
        fail('DANGLING_ESCAPE', index);
      }

      const escaped = source[index + 1];
      if (escaped !== '"' && escaped !== '\\') {
        fail('INVALID_ESCAPE', index);
      }
      value += escaped;
      index += 2;
      continue;
    }

    value += character;
    index += 1;
  }

  fail('UNCLOSED_QUOTE', quoteIndex);
}

function assertOperandLength(value, index) {
  const length = characterLength(value);
  if (length > EMAIL_SEARCH_LIMITS.operandLength) {
    fail('OPERAND_TOO_LONG', index, undefined, length);
  }
}

function assertQuotedBoundary(source, index) {
  if (index >= source.length || isWhitespace(source[index])) return;
  if (source[index] === '(' || source[index] === ')') {
    fail('UNQUOTED_PARENTHESIS', index);
  }
  fail('MISSING_SEPARATOR', index);
}

function scanUnquoted(source, start) {
  let index = start;
  while (index < source.length && !isWhitespace(source[index])) {
    if (source[index] === '(' || source[index] === ')') {
      fail('UNQUOTED_PARENTHESIS', index);
    }
    if (source[index] === '"') {
      fail('UNEXPECTED_QUOTE', index);
    }
    if (source[index] === '\\' && index === source.length - 1) {
      fail('DANGLING_ESCAPE', index);
    }
    index += 1;
  }
  return index;
}

function isLeapYear(year) {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function isCalendarDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year === 0 || month < 1 || month > 12 || day < 1) return false;

  const daysByMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= daysByMonth[month - 1];
}

function validateOperatorValue(operator, value, index) {
  const normalizedValue = value.toLowerCase();
  const allowedValues = VALUE_DEFINITIONS[operator];
  if (allowedValues && !allowedValues.includes(normalizedValue)) {
    const message = `Unsupported value for "${operator}:". Use ${allowedValues.join(', ')}.`;
    fail('INVALID_VALUE', index, message, value.length);
  }

  if ((operator === 'after' || operator === 'before') && !isCalendarDate(value)) {
    fail('INVALID_DATE', index, `Use a valid YYYY-MM-DD date after "${operator}:".`, value.length);
  }

  return normalizedValue;
}

function makeClause({ source, start, end, value, quoted, negated, operator, index, groupIndex }) {
  assertOperandLength(value, start);

  if (!value) {
    if (operator) fail('EMPTY_OPERAND', start, `Add a value after "${operator}:".`);
    fail('EMPTY_TERM', start);
  }

  const normalizedValue = operator
    ? validateOperatorValue(operator, value, start)
    : value;
  const clause = {
    id: `clause-${index}`,
    index,
    groupIndex,
    type: operator ? 'operator' : 'text',
    operator: operator || null,
    value,
    normalizedValue,
    negated,
    quoted,
    exact: quoted,
    raw: source.slice(start, end),
    start,
    end,
  };
  clause.token = serializeEmailSearchClause(clause);
  clause.label = formatEmailSearchClause(clause);
  return clause;
}

function parseClause(source, initialIndex, clauseIndex, groupIndex) {
  const start = initialIndex;
  let index = initialIndex;
  let negated = false;

  if (source[index] === '-') {
    negated = true;
    index += 1;
    if (source[index] === '-') fail('MULTIPLE_NEGATION', index);
    if (index >= source.length || isWhitespace(source[index])) {
      fail('EMPTY_NEGATION', start);
    }
  }

  if (source[index] === '"') {
    const quoted = readQuoted(source, index);
    assertQuotedBoundary(source, quoted.end);
    return makeClause({
      source,
      start,
      end: quoted.end,
      value: quoted.value,
      quoted: true,
      negated,
      operator: null,
      index: clauseIndex,
      groupIndex,
    });
  }

  const operatorMatch = /^([A-Za-z]+):/.exec(source.slice(index));
  const candidate = operatorMatch?.[1]?.toLowerCase();
  const operator = OPERATOR_BY_NAME.has(candidate) ? candidate : null;

  if (operator) {
    const operandStart = index + operatorMatch[0].length;
    if (operandStart >= source.length || isWhitespace(source[operandStart])) {
      fail('EMPTY_OPERAND', operandStart, `Add a value after "${operator}:".`, 0);
    }

    if (source[operandStart] === '"') {
      const quoted = readQuoted(source, operandStart);
      assertQuotedBoundary(source, quoted.end);
      return makeClause({
        source,
        start,
        end: quoted.end,
        value: quoted.value,
        quoted: true,
        negated,
        operator,
        index: clauseIndex,
        groupIndex,
      });
    }

    const end = scanUnquoted(source, operandStart);
    return makeClause({
      source,
      start,
      end,
      value: source.slice(operandStart, end),
      quoted: false,
      negated,
      operator,
      index: clauseIndex,
      groupIndex,
    });
  }

  const end = scanUnquoted(source, index);
  return makeClause({
    source,
    start,
    end,
    value: source.slice(index, end),
    quoted: false,
    negated,
    operator: null,
    index: clauseIndex,
    groupIndex,
  });
}

/**
 * Parse a query into OR groups containing implicitly ANDed clauses.
 *
 * @throws {EmailSearchParseError} for invalid grammar or limit violations.
 */
export function parseEmailSearch(input) {
  const source = String(input ?? '');
  const sourceLength = characterLength(source);
  if (sourceLength > EMAIL_SEARCH_LIMITS.queryLength) {
    fail('QUERY_TOO_LONG', EMAIL_SEARCH_LIMITS.queryLength, undefined, source.length - EMAIL_SEARCH_LIMITS.queryLength);
  }

  const groups = [];
  const clauses = [];
  const tokens = [];
  let currentGroup = [];
  let index = 0;
  let trailingOr = null;

  while (index < source.length) {
    while (index < source.length && isWhitespace(source[index])) index += 1;
    if (index >= source.length) break;

    if (isStandaloneOr(source, index)) {
      if (currentGroup.length === 0) {
        fail(clauses.length === 0 ? 'LEADING_OR' : 'CONSECUTIVE_OR', index, undefined, 2);
      }

      groups.push(currentGroup);
      currentGroup = [];
      tokens.push({ type: 'or', raw: source.slice(index, index + 2), start: index, end: index + 2 });
      trailingOr = index;
      index += 2;
      continue;
    }

    if (clauses.length >= EMAIL_SEARCH_LIMITS.clauses) {
      fail('TOO_MANY_CLAUSES', index);
    }

    const clause = parseClause(source, index, clauses.length, groups.length);
    clauses.push(clause);
    currentGroup.push(clause);
    tokens.push(clause);
    trailingOr = null;
    index = clause.end;
  }

  if (trailingOr != null) {
    fail('TRAILING_OR', trailingOr, undefined, 2);
  }
  if (currentGroup.length > 0) groups.push(currentGroup);

  const ast = {
    type: 'email-search',
    source,
    groups,
    clauses,
    tokens,
  };
  ast.normalizedQuery = serializeEmailSearch(ast);
  return ast;
}

function errorDetails(error) {
  if (error instanceof EmailSearchParseError) return error.toJSON();
  return {
    code: 'INVALID_INPUT',
    message: ERROR_MESSAGES.INVALID_INPUT,
    index: 0,
    length: 1,
  };
}

/**
 * UI-safe parser facade. It always returns a result object and never leaks a
 * parser or input-conversion exception to an input event handler.
 */
export function analyzeEmailSearch(input) {
  let query = '';
  try {
    query = String(input ?? '');
    const ast = parseEmailSearch(query);
    return {
      valid: true,
      query,
      ast,
      parsed: ast,
      groups: ast.groups,
      clauses: ast.clauses,
      chips: getEmailSearchChips(ast),
      normalizedQuery: ast.normalizedQuery,
      error: null,
      errors: [],
      suggestions: getEmailSearchSuggestions(query),
    };
  } catch (error) {
    const detail = errorDetails(error);
    return {
      valid: false,
      query,
      ast: null,
      parsed: null,
      groups: [],
      clauses: [],
      chips: [],
      normalizedQuery: '',
      error: detail,
      errors: [detail],
      suggestions: getEmailSearchSuggestions(query),
    };
  }
}

function quoteValue(value) {
  return `"${String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function textNeedsQuotes(value) {
  return !value
    || /[\s()"\\]/u.test(value)
    || value.toLowerCase() === 'or'
    || value.startsWith('-');
}

export function serializeEmailSearchClause(clause) {
  const operator = clause?.operator ? `${String(clause.operator).toLowerCase()}:` : '';
  const value = String(clause?.value ?? '');
  const shouldQuote = Boolean(clause?.quoted)
    || (operator ? /[\s()"\\]/u.test(value) : textNeedsQuotes(value));
  const operand = shouldQuote ? quoteValue(value) : value;
  return `${clause?.negated ? '-' : ''}${operator}${operand}`;
}

export function serializeEmailSearch(input) {
  const parsed = typeof input === 'string' ? parseEmailSearch(input) : input;
  const groups = Array.isArray(parsed?.groups)
    ? parsed.groups
    : (Array.isArray(parsed?.clauses) ? [parsed.clauses] : []);

  return groups
    .filter(group => Array.isArray(group) && group.length > 0)
    .map(group => group.map(serializeEmailSearchClause).join(' '))
    .join(' OR ');
}

export function formatEmailSearchClause(clause) {
  const value = String(clause?.value ?? '');
  let label;
  if (clause?.operator) {
    const definition = OPERATOR_BY_NAME.get(String(clause.operator).toLowerCase());
    label = `${definition?.label || clause.operator}: ${value}`;
  } else {
    label = clause?.quoted ? `"${value}"` : value;
  }
  return clause?.negated ? `Not ${label}` : label;
}

export const getEmailSearchClauseLabel = formatEmailSearchClause;

export function getEmailSearchChips(input) {
  const parsed = typeof input === 'string' ? parseEmailSearch(input) : input;
  const clauses = Array.isArray(parsed?.clauses) ? parsed.clauses : [];
  let previousGroup = null;

  return clauses.map((clause, index) => {
    const join = index === 0 ? null : (clause.groupIndex === previousGroup ? 'and' : 'or');
    previousGroup = clause.groupIndex;
    return {
      id: clause.id,
      index: clause.index,
      groupIndex: clause.groupIndex,
      join,
      label: formatEmailSearchClause(clause),
      token: serializeEmailSearchClause(clause),
      operator: clause.operator,
      value: clause.value,
      negated: clause.negated,
      quoted: clause.quoted,
    };
  });
}

export function getEmailSearchScopeLabel(input) {
  const parsed = typeof input === 'string' ? parseEmailSearch(input) : input;
  if (!parsed || !Array.isArray(parsed.groups)) return 'Structured search results';

  const scopes = new Set();
  for (const group of parsed.groups) {
    const groupScopes = group
      .filter(clause => clause.operator === 'in' && !clause.negated)
      .map(clause => clause.normalizedValue);
    if (groupScopes.length === 0) scopes.add('regular');
    for (const scope of groupScopes) scopes.add(scope);
  }

  if (scopes.size === 0 || (scopes.size === 1 && scopes.has('regular'))) {
    return 'All regular mail';
  }
  if (scopes.size > 1) return 'Matching mail across selected folders';
  return {
    inbox: 'Inbox results',
    sent: 'Sent-mail results',
    drafts: 'Draft results',
    archive: 'Archived-mail results',
    starred: 'Starred-mail results',
    spam: 'Spam results',
    trash: 'Trash results',
    all: 'All regular mail',
    anywhere: 'All mail, including spam and trash',
  }[[...scopes][0]] || 'Structured search results';
}

function clauseMatchesTarget(clause, target) {
  if (typeof target === 'number') return clause.index === target;
  if (typeof target === 'string') return clause.id === target;
  if (!target || typeof target !== 'object') return false;
  return clause === target
    || (target.id != null && clause.id === target.id)
    || (target.index != null && clause.index === target.index);
}

/** Remove one clause and collapse an empty OR group, returning a valid query. */
export function removeEmailSearchClause(input, target) {
  const parsed = typeof input === 'string' ? parseEmailSearch(input) : input;
  if (!parsed || !Array.isArray(parsed.groups)) return '';

  const groups = parsed.groups
    .map(group => group.filter(clause => !clauseMatchesTarget(clause, target)))
    .filter(group => group.length > 0);
  return serializeEmailSearch({ groups });
}

function currentSuggestionFragment(query, cursor) {
  const beforeCursor = query.slice(0, cursor);
  if (!beforeCursor || /\s$/u.test(beforeCursor)) return '';
  const match = /[^\s]+$/u.exec(beforeCursor);
  return match?.[0] || '';
}

/** Return operator or enumerated-value suggestions for the active token. */
export function getEmailSearchSuggestions(input = '', cursor = null) {
  let query;
  try {
    query = String(input ?? '');
  } catch {
    return [];
  }

  const requestedCursor = cursor == null ? query.length : Number(cursor);
  const safeCursor = Number.isFinite(requestedCursor)
    ? Math.max(0, Math.min(query.length, Math.trunc(requestedCursor)))
    : query.length;
  let fragment = currentSuggestionFragment(query, safeCursor);
  if (fragment.startsWith('-')) fragment = fragment.slice(1);
  if (fragment.includes('"') || fragment.includes('(') || fragment.includes(')')) return [];

  const colonIndex = fragment.indexOf(':');
  if (colonIndex >= 0) {
    const operator = fragment.slice(0, colonIndex).toLowerCase();
    const definition = OPERATOR_BY_NAME.get(operator);
    if (!definition?.values) return [];

    const valuePrefix = fragment.slice(colonIndex + 1).toLowerCase();
    return definition.values
      .filter(value => value.startsWith(valuePrefix))
      .map(value => ({
        type: 'value',
        operator,
        value,
        label: value,
        syntax: `${operator}:${value}`,
        insertText: `${operator}:${value}`,
        replacement: value,
        description: `${definition.label}: ${value}`,
      }));
  }

  const prefix = fragment.toLowerCase();
  return EMAIL_SEARCH_OPERATORS
    .filter(definition => !prefix || definition.operator.startsWith(prefix))
    .map(definition => ({ ...definition, type: 'operator' }));
}

// Concise aliases for callers that already sit in an email-search namespace.
export const parseSearchQuery = parseEmailSearch;
export const analyzeSearchQuery = analyzeEmailSearch;
export const removeSearchClause = removeEmailSearchClause;
export const searchSuggestions = getEmailSearchSuggestions;
