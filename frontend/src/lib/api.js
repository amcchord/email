import { captureAuthEpoch, isAuthEpochCurrent } from './authSession.js';

const BASE = '/api';

let onUnauthorized = null;
const refreshPromises = new Map();
let explicitRefreshSequence = 0;
let logoutPromise = null;
let logoutBlocksRefresh = false;

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

function authEpochKey(snapshot) {
  return `${snapshot.generation}:${snapshot.userId ?? 'anonymous'}`;
}

function assertAuthEpochCurrent(snapshot) {
  if (isAuthEpochCurrent(snapshot)) return;
  const error = new Error('Authentication session changed');
  error.name = 'AbortError';
  error.code = 'auth_session_changed';
  throw error;
}

function authLogoutInProgressError() {
  const error = new Error('Authentication logout is in progress');
  error.name = 'AbortError';
  error.code = 'auth_logout_in_progress';
  return error;
}

async function attemptTokenRefresh(requestEpoch) {
  assertAuthEpochCurrent(requestEpoch);
  // A refresh response mutates HttpOnly auth cookies before JavaScript can
  // inspect it. Once logout starts, no later refresh may be allowed to put the
  // prior identity's cookies back after the ordered cookie clear.
  if (logoutBlocksRefresh) return false;
  const key = authEpochKey(requestEpoch);
  const existing = refreshPromises.get(key);
  if (existing) return existing;

  let refreshPromise;
  refreshPromise = fetch(`${BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({}),
  }).then(resp => {
    return isAuthEpochCurrent(requestEpoch) && resp.ok;
  }).catch(() => {
    return false;
  }).finally(() => {
    if (refreshPromises.get(key) === refreshPromise) refreshPromises.delete(key);
  });

  refreshPromises.set(key, refreshPromise);
  return refreshPromise;
}

async function drainTokenRefreshes() {
  while (refreshPromises.size > 0) {
    await Promise.allSettled([...refreshPromises.values()]);
  }
}

export async function waitForAuthCookieBarrier() {
  while (logoutPromise) {
    const pendingLogout = logoutPromise;
    await pendingLogout.catch(() => {});
    if (logoutPromise === pendingLogout) break;
  }
}

async function request(method, path, body = null, options = {}) {
  const requestEpoch = captureAuthEpoch();
  const { responseType = 'json', skipAuthRefresh = false, ...fetchOptions } = options;
  const headers = { ...fetchOptions.headers };
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const config = {
    method,
    credentials: 'include',
    ...fetchOptions,
    headers,
  };

  if (body) {
    config.body = body instanceof FormData ? body : JSON.stringify(body);
  }

  let response = await fetch(`${BASE}${path}`, config);
  assertAuthEpochCurrent(requestEpoch);

  // On 401, try to refresh the token and retry once
  if (response.status === 401 && !skipAuthRefresh && !path.includes('/auth/refresh')) {
    const refreshed = await attemptTokenRefresh(requestEpoch);
    assertAuthEpochCurrent(requestEpoch);
    if (refreshed) {
      // Rebuild config for retry (body may be consumed)
      const retryConfig = {
        method,
        credentials: 'include',
        ...fetchOptions,
        headers: { ...fetchOptions.headers },
      };
      if (body && !(body instanceof FormData)) {
        retryConfig.headers['Content-Type'] = 'application/json';
      }
      if (body) {
        retryConfig.body = body instanceof FormData ? body : JSON.stringify(body);
      }
      response = await fetch(`${BASE}${path}`, retryConfig);
      assertAuthEpochCurrent(requestEpoch);
    }

    if (response.status === 401) {
      assertAuthEpochCurrent(requestEpoch);
      // Logout owns the final cookie mutation. Do not publish anonymous state
      // from a concurrent 401 before its cookie-clearing response has landed.
      if (logoutBlocksRefresh) throw authLogoutInProgressError();
      if (onUnauthorized) {
        onUnauthorized();
      }
      const unauthorizedError = new Error('Unauthorized');
      unauthorizedError.status = 401;
      throw unauthorizedError;
    }
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    assertAuthEpochCurrent(requestEpoch);
    const detail = error?.detail;
    const errorMessage = typeof detail === 'string'
      ? detail
      : (typeof detail?.message === 'string' ? detail.message : `HTTP ${response.status}`);
    const requestError = new Error(errorMessage);
    requestError.status = response.status;
    if (typeof detail?.code === 'string') requestError.code = detail.code;
    if (detail && typeof detail === 'object') requestError.detail = detail;
    throw requestError;
  }

  if (response.status === 204) return null;
  if (responseType === 'blob') {
    const blob = await response.blob();
    assertAuthEpochCurrent(requestEpoch);
    return blob;
  }
  if (responseType === 'attachmentPreview') {
    const blob = await response.blob();
    assertAuthEpochCurrent(requestEpoch);
    return {
      blob,
      kind: response.headers.get('X-Attachment-Preview-Kind'),
      truncated: response.headers.get('X-Attachment-Preview-Truncated') === 'true',
      contentType: response.headers.get('Content-Type') || blob.type,
    };
  }
  const result = await response.json();
  assertAuthEpochCurrent(requestEpoch);
  return result;
}

function orderedLogout() {
  if (logoutPromise) return logoutPromise;

  logoutBlocksRefresh = true;
  const operation = (async () => {
    // Responses from these requests may carry Set-Cookie. Drain them before
    // sending the final cookie-clearing response so network completion order
    // cannot resurrect the identity that is signing out.
    await drainTokenRefreshes();
    return request('POST', '/auth/logout', null, { skipAuthRefresh: true });
  })();

  let trackedLogout;
  trackedLogout = operation.finally(() => {
    if (logoutPromise === trackedLogout) {
      logoutPromise = null;
    }
  });
  logoutPromise = trackedLogout;
  return trackedLogout;
}

async function orderedLogin(username, password) {
  await waitForAuthCookieBarrier();
  const result = await request('POST', '/auth/login', { username, password }, { skipAuthRefresh: true });
  // A successful login has authoritatively replaced any cookies that survived
  // a failed logout. Automatic refreshes may resume for this new session.
  logoutBlocksRefresh = false;
  return result;
}

async function orderedGoogleLoginStart() {
  await waitForAuthCookieBarrier();
  return request('GET', '/auth/google/login', null, { skipAuthRefresh: true });
}

async function trackedExplicitRefresh() {
  if (logoutBlocksRefresh) {
    throw authLogoutInProgressError();
  }
  const requestEpoch = captureAuthEpoch();
  assertAuthEpochCurrent(requestEpoch);
  const key = `${authEpochKey(requestEpoch)}:explicit:${++explicitRefreshSequence}`;
  const refreshPromise = request('POST', '/auth/refresh', {}, { skipAuthRefresh: true });
  refreshPromises.set(key, refreshPromise);
  try {
    return await refreshPromise;
  } finally {
    if (refreshPromises.get(key) === refreshPromise) refreshPromises.delete(key);
  }
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  delete: (path) => request('DELETE', path),

  // Auth
  login: orderedLogin,
  startGoogleLogin: orderedGoogleLoginStart,
  logout: orderedLogout,
  me: () => request('GET', '/auth/me'),
  refresh: trackedExplicitRefresh,

  // API Tokens (for the read-only public /api/v1 surface)
  listApiTokens: () => request('GET', '/auth/api-tokens'),
  createApiToken: (name) => request('POST', '/auth/api-tokens', { name }),
  revokeApiToken: (id) => request('DELETE', `/auth/api-tokens/${id}`),

  // E-Ink Terminals (per-user short-code dashboards + Home Assistant link)
  getTerminalSettings: () => request('GET', '/terminal/settings'),
  regenerateTerminalCode: () => request('POST', '/terminal/settings/regenerate', {}),
  setHomeAssistant: (payload) => request('PUT', '/terminal/settings/home-assistant', payload),
  setTerminalTimezone: (timezone) => request('PUT', '/terminal/settings/timezone', { timezone }),
  listTerminals: () => request('GET', '/terminal/devices'),
  updateTerminal: (id, payload) => request('PATCH', `/terminal/devices/${id}`, payload),
  deleteTerminal: (id) => request('DELETE', `/terminal/devices/${id}`),
  testHomeAssistant: () => request('POST', '/terminal/ha/test', {}),
  // URL builder for the post-quantize preview <img>; uses cookie auth.
  terminalPreviewPngUrl: (id, palette = null, cacheBuster = null) => {
    const params = new URLSearchParams();
    if (palette) params.set('palette', palette);
    if (cacheBuster) params.set('t', String(cacheBuster));
    const qs = params.toString();
    let q = '';
    if (qs) q = `?${qs}`;
    return `/api/terminal/devices/${id}/preview.png${q}`;
  },

  // Emails
  listEmails: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/emails/?${searchParams.toString()}`);
  },
  getEmail: (id) => request('GET', `/emails/${id}`),
  downloadAttachment: (emailId, attachmentId, options = {}) =>
    request(
      'GET',
      `/emails/${emailId}/attachments/${attachmentId}/download`,
      null,
      { ...options, responseType: 'blob' },
    ),
  previewAttachment: (emailId, attachmentId, options = {}) =>
    request(
      'GET',
      `/emails/${emailId}/attachments/${attachmentId}/preview`,
      null,
      { ...options, responseType: 'attachmentPreview' },
    ),
  attachmentPreviewUrl: (emailId, attachmentId) =>
    `/api/emails/${encodeURIComponent(emailId)}/attachments/${encodeURIComponent(attachmentId)}/preview`,
  getThread: (threadId, order = null, accountId = null) => {
    const params = new URLSearchParams();
    if (order) params.set('order', order);
    if (accountId) params.set('account_id', String(accountId));
    const query = params.toString();
    return request('GET', `/emails/thread/${threadId}${query ? `?${query}` : ''}`);
  },
  emailActions: (emailIds, action, idempotencyKey = null) =>
    request('POST', '/emails/actions', {
      email_ids: emailIds,
      action,
      ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {}),
    }),
  getMailAction: (requestId) => request('GET', `/emails/actions/${requestId}`),
  getMailActionByIdempotency: (idempotencyKey) =>
    request('GET', `/emails/actions/by-idempotency/${idempotencyKey}`),
  listRecentMailActions: (limit = 20) =>
    request('GET', `/emails/actions/recent?limit=${encodeURIComponent(limit)}`),
  undoMailAction: (requestId) => request('POST', `/emails/actions/${requestId}/undo`, {}),
  retryMailAction: (requestId) => request('POST', `/emails/actions/${requestId}/retry`, {}),
  getLabels: (accountId = null) => {
    const params = accountId ? `?account_id=${accountId}` : '';
    return request('GET', `/emails/labels/all${params}`);
  },

  // Compose
  sendEmail: (data, idempotencyKey = data?.idempotency_key) => {
    if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim()) {
      throw new Error('A send idempotency key is required');
    }
    return request('POST', '/compose/send', {
      ...data,
      idempotency_key: idempotencyKey,
    });
  },
  listRecentOutboundSends: (limit = 20) =>
    request('GET', `/compose/sends/recent?limit=${encodeURIComponent(limit)}`),
  getOutboundSendByIdempotency: (idempotencyKey) =>
    request('GET', `/compose/sends/by-idempotency/${encodeURIComponent(idempotencyKey)}`),
  getOutboundSend: (sendId) =>
    request('GET', `/compose/sends/${encodeURIComponent(sendId)}`),
  undoOutboundSend: (sendId) =>
    request('POST', `/compose/sends/${encodeURIComponent(sendId)}/undo`, {}),
  retryOutboundSend: (sendId) =>
    request('POST', `/compose/sends/${encodeURIComponent(sendId)}/retry`, {}),
  saveDraft: (data) => {
    if (typeof data?.client_draft_id !== 'string' || !data.client_draft_id.trim()) {
      throw new Error('A client draft ID is required');
    }
    if (!Number.isSafeInteger(Number(data?.revision)) || Number(data.revision) < 1) {
      throw new Error('A positive draft revision is required');
    }
    if (typeof data?.mutation_id !== 'string' || !data.mutation_id.trim()) {
      throw new Error('A draft mutation ID is required');
    }
    return request('POST', '/compose/draft', data);
  },
  getComposeDraft: (clientDraftId) =>
    request('GET', `/compose/drafts/by-client-id/${encodeURIComponent(clientDraftId)}`),
  getComposeDraftByEmail: (emailId) =>
    request('GET', `/compose/drafts/by-email/${encodeURIComponent(emailId)}`),
  getComposeDraftBySource: (emailId, accountId) => {
    const params = new URLSearchParams({ account_id: String(accountId) });
    return request('GET', `/compose/drafts/by-source-email/${encodeURIComponent(emailId)}?${params}`);
  },
  listRecentComposeDrafts: (limit = 20) =>
    request('GET', `/compose/drafts/recent?limit=${encodeURIComponent(limit)}`),
  discardComposeDraft: (clientDraftId, mutationId) =>
    request('POST', `/compose/drafts/${encodeURIComponent(clientDraftId)}/discard`, {
      mutation_id: mutationId,
    }),
  undoComposeDraftDiscard: (clientDraftId, mutationId) =>
    request('POST', `/compose/drafts/${encodeURIComponent(clientDraftId)}/undo-discard`, {
      mutation_id: mutationId,
    }),

  // Accounts
  listAccounts: () => request('GET', '/accounts/'),
  startOAuth: () => request('GET', '/accounts/oauth/start'),
  reauthorizeAccount: (accountId, { returnPage = 'admin' } = {}) => {
    const params = new URLSearchParams({
      return_page: returnPage === 'calendar' ? 'calendar' : 'admin',
    });
    return request('GET', `/accounts/${accountId}/reauthorize?${params.toString()}`);
  },
  triggerSync: (accountId) => request('POST', `/accounts/${accountId}/sync`),
  getSyncStatus: (accountId) => request('GET', `/accounts/${accountId}/sync-status`),

  // Admin
  getFeatureFlags: () => request('GET', '/admin/feature-flags'),
  getDashboard: () => request('GET', '/admin/dashboard'),
  getStats: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') searchParams.set(key, value);
    }
    const query = searchParams.toString();
    return request('GET', `/admin/stats${query ? `?${query}` : ''}`);
  },
  getSettings: () => request('GET', '/admin/settings'),
  updateSetting: (data) => request('PUT', '/admin/settings', data),
  deleteSetting: (key) => request('DELETE', `/admin/settings/${key}`),
  getAdminAccounts: () => request('GET', '/admin/accounts'),
  removeAccount: (accountId) => request('DELETE', `/admin/accounts/${accountId}`),

  // AI
  analyzeEmail: (emailId) => request('POST', `/ai/analyze/${emailId}`),
  analyzeThread: (threadId) => request('POST', `/ai/analyze/thread/${threadId}`),
  getAITrends: () => request('GET', '/ai/trends'),
  getAIStats: () => request('GET', '/ai/stats'),
  triggerAutoCategorize: (days = null) => {
    const qs = days !== null ? `?days=${days}` : '';
    return request('POST', `/ai/auto-categorize${qs}`);
  },
  deleteAIAnalyses: (rebuildDays = null) => {
    const qs = rebuildDays !== null ? `?rebuild_days=${rebuildDays}` : '';
    return request('DELETE', `/ai/analyses${qs}`);
  },
  getAIProcessingStatus: () => request('GET', '/ai/processing/status'),
  rebuildSearchIndex: (accountId = null) => {
    const qs = accountId ? `?account_id=${accountId}` : '';
    return request('POST', `/ai/rebuild-search-index${qs}`);
  },
  generateReply: (emailId, prompt) =>
    request('POST', '/ai/generate-reply', { email_id: emailId, prompt }),
  getNeedsReply: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/needs-reply?${searchParams.toString()}`);
  },
  ignoreNeedsReply: (emailId) =>
    request('POST', `/ai/needs-reply/${emailId}/ignore`),
  unignoreNeedsReply: (emailId) =>
    request('POST', `/ai/needs-reply/${emailId}/unignore`),
  snoozeNeedsReply: (emailId, duration) =>
    request('POST', `/ai/needs-reply/${emailId}/snooze?duration=${duration}`),
  unsnoozeNeedsReply: (emailId) =>
    request('POST', `/ai/needs-reply/${emailId}/unsnooze`),
  getNeedsReplyIgnored: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/needs-reply/ignored?${searchParams.toString()}`);
  },
  getNeedsReplySnoozed: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/needs-reply/snoozed?${searchParams.toString()}`);
  },
  getSubscriptions: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/subscriptions?${searchParams.toString()}`);
  },
  unsubscribe: (emailId, { preview = false, markSpam = true } = {}) => {
    const params = new URLSearchParams();
    if (preview) params.set('preview', 'true');
    if (!markSpam) params.set('mark_spam', 'false');
    const qs = params.toString();
    return request('POST', `/ai/unsubscribe/${emailId}${qs ? '?' + qs : ''}`);
  },
  unsubscribeStream: async (emailId, { markSpam = true, signal = null } = {}) => {
    const requestEpoch = captureAuthEpoch();
    const params = new URLSearchParams();
    if (!markSpam) params.set('mark_spam', 'false');
    const qs = params.toString();
    const response = await fetch(`${BASE}/ai/unsubscribe/${emailId}/stream${qs ? '?' + qs : ''}`, {
      method: 'GET',
      credentials: 'include',
      signal,
    });
    assertAuthEpochCurrent(requestEpoch);
    return response;
  },
  bulkUnsubscribe: (emailIds, { markSpam = true } = {}) => {
    const params = new URLSearchParams();
    for (const id of emailIds) {
      params.append('email_ids', id);
    }
    if (!markSpam) params.set('mark_spam', 'false');
    return request('POST', `/ai/unsubscribe/bulk?${params.toString()}`);
  },
  blockSender: (emailId) => request('POST', `/ai/subscriptions/${emailId}/block`),
  getThreadSummaries: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/threads?${searchParams.toString()}`);
  },
  getThreadDigests: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/digests?${searchParams.toString()}`);
  },
  getAwaitingResponse: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/awaiting-response?${searchParams.toString()}`);
  },
  getEmailBundles: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/bundles?${searchParams.toString()}`);
  },

  // Todos
  getTodos: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/todos/?${searchParams.toString()}`);
  },
  createTodo: (data) => request('POST', '/todos/', data),
  createTodosFromEmail: (emailId) => request('POST', `/todos/from-email/${emailId}`),
  updateTodo: (id, data) => request('PATCH', `/todos/${id}`, data),
  deleteTodo: (id) => request('DELETE', `/todos/${id}`),

  // AI Actions
  draftAction: (todoId) => request('POST', '/ai/draft-action', { todo_id: todoId }),
  approveAction: (todoId) => request('POST', `/ai/approve-action/${todoId}`),
  reprocessEmails: (model) => request('POST', '/ai/reprocess', { model }),

  // Chat
  chatStream: async (message, conversationId = null, { signal = null } = {}) => {
    const requestEpoch = captureAuthEpoch();
    // Returns the raw Response for SSE streaming -- caller reads the stream
    const response = await fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ message, conversation_id: conversationId }),
      signal,
    });
    assertAuthEpochCurrent(requestEpoch);
    return response;
  },
  getConversations: () => request('GET', '/chat/conversations'),
  getConversation: (id) => request('GET', `/chat/conversations/${id}`),
  deleteConversation: (id) => request('DELETE', `/chat/conversations/${id}`),

  // Calendar
  getCalendarEvents: (params = {}, options = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/calendar/events?${searchParams.toString()}`, null, options);
  },
  getCalendarEvent: (id) => request('GET', `/calendar/events/${id}`),
  triggerCalendarSync: (accountId = null) => {
    const qs = accountId ? `?account_id=${accountId}` : '';
    return request('POST', `/calendar/sync${qs}`);
  },
  getCalendarSyncStatus: (options = {}) => request('GET', '/calendar/sync-status', null, options),
  getUpcomingEvents: (days = 7) => request('GET', `/calendar/upcoming?days=${days}`),

  // AI Preferences
  getAIPreferences: () => request('GET', '/auth/ai-preferences'),
  updateAIPreferences: (prefs) => request('PUT', '/auth/ai-preferences', prefs),

  // About Me
  getAboutMe: () => request('GET', '/auth/about-me'),
  updateAboutMe: (aboutMe) => request('PUT', '/auth/about-me', { about_me: aboutMe }),

  // Keyboard Shortcuts
  getKeyboardShortcuts: () => request('GET', '/auth/keyboard-shortcuts'),
  updateKeyboardShortcuts: (shortcuts) => request('PUT', '/auth/keyboard-shortcuts', { shortcuts }),

  // UI Preferences
  getUIPreferences: () => request('GET', '/auth/ui-preferences'),
  updateUIPreferences: (prefs) => request('PUT', '/auth/ui-preferences', prefs),

  // Account description
  updateAccountDescription: (accountId, description) =>
    request('PUT', `/accounts/${accountId}/description`, { description }),

  // Device code auth (for TUI)
  deviceAuthorize: (userCode) => request('POST', '/auth/device/authorize', { user_code: userCode }),

  // Health
  health: () => request('GET', '/health'),
};
