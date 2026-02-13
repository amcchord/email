const BASE = '/api';

let onUnauthorized = null;
let isRefreshing = false;
let refreshPromise = null;

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

async function attemptTokenRefresh() {
  // If already refreshing, wait for the existing attempt
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  isRefreshing = true;
  refreshPromise = fetch(`${BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({}),
  }).then(resp => {
    if (resp.ok) {
      return true;
    }
    return false;
  }).catch(() => {
    return false;
  }).finally(() => {
    isRefreshing = false;
    refreshPromise = null;
  });

  return refreshPromise;
}

async function request(method, path, body = null, options = {}) {
  const headers = { ...options.headers };
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const config = {
    method,
    headers,
    credentials: 'include',
    ...options,
  };

  if (body) {
    config.body = body instanceof FormData ? body : JSON.stringify(body);
  }

  let response = await fetch(`${BASE}${path}`, config);

  // On 401, try to refresh the token and retry once
  if (response.status === 401 && !path.includes('/auth/refresh')) {
    const refreshed = await attemptTokenRefresh();
    if (refreshed) {
      // Rebuild config for retry (body may be consumed)
      const retryConfig = {
        method,
        headers: { ...options.headers },
        credentials: 'include',
        ...options,
      };
      if (body && !(body instanceof FormData)) {
        retryConfig.headers['Content-Type'] = 'application/json';
      }
      if (body) {
        retryConfig.body = body instanceof FormData ? body : JSON.stringify(body);
      }
      response = await fetch(`${BASE}${path}`, retryConfig);
    }

    if (response.status === 401) {
      if (onUnauthorized) {
        onUnauthorized();
      }
      throw new Error('Unauthorized');
    }
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  delete: (path) => request('DELETE', path),

  // Auth
  login: (username, password) => request('POST', '/auth/login', { username, password }),
  logout: () => request('POST', '/auth/logout'),
  me: () => request('GET', '/auth/me'),
  refresh: () => request('POST', '/auth/refresh', {}),

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
  getThread: (threadId) => request('GET', `/emails/thread/${threadId}`),
  emailActions: (emailIds, action, label = null) =>
    request('POST', '/emails/actions', { email_ids: emailIds, action, label }),
  getLabels: (accountId = null) => {
    const params = accountId ? `?account_id=${accountId}` : '';
    return request('GET', `/emails/labels/all${params}`);
  },

  // Compose
  sendEmail: (data) => request('POST', '/compose/send', data),
  saveDraft: (data) => request('POST', '/compose/draft', data),

  // Accounts
  listAccounts: () => request('GET', '/accounts/'),
  startOAuth: () => request('GET', '/accounts/oauth/start'),
  reauthorizeAccount: (accountId) => request('GET', `/accounts/${accountId}/reauthorize`),
  triggerSync: (accountId) => request('POST', `/accounts/${accountId}/sync`),
  getSyncStatus: (accountId) => request('GET', `/accounts/${accountId}/sync-status`),

  // Admin
  getDashboard: () => request('GET', '/admin/dashboard'),
  getStats: () => request('GET', '/admin/stats'),
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
  getNeedsReply: (params = {}) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        searchParams.set(key, value);
      }
    }
    return request('GET', `/ai/needs-reply?${searchParams.toString()}`);
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
  unsubscribe: (emailId, preview = false) => {
    const qs = preview ? '?preview=true' : '';
    return request('POST', `/ai/unsubscribe/${emailId}${qs}`);
  },
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
  chatStream: (message, conversationId = null) => {
    // Returns the raw Response for SSE streaming -- caller reads the stream
    return fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });
  },
  getConversations: () => request('GET', '/chat/conversations'),
  getConversation: (id) => request('GET', `/chat/conversations/${id}`),
  deleteConversation: (id) => request('DELETE', `/chat/conversations/${id}`),

  // AI Preferences
  getAIPreferences: () => request('GET', '/auth/ai-preferences'),
  updateAIPreferences: (prefs) => request('PUT', '/auth/ai-preferences', prefs),

  // About Me
  getAboutMe: () => request('GET', '/auth/about-me'),
  updateAboutMe: (aboutMe) => request('PUT', '/auth/about-me', { about_me: aboutMe }),

  // Account description
  updateAccountDescription: (accountId, description) =>
    request('PUT', `/accounts/${accountId}/description`, { description }),

  // Health
  health: () => request('GET', '/health'),
};
