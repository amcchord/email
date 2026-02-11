const BASE = '/api';

let onUnauthorized = null;

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
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

  const response = await fetch(`${BASE}${path}`, config);

  if (response.status === 401) {
    if (onUnauthorized) {
      onUnauthorized();
    }
    throw new Error('Unauthorized');
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
  refresh: (refresh_token) => request('POST', '/auth/refresh', { refresh_token }),

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
  triggerSync: (accountId) => request('POST', `/accounts/${accountId}/sync`),
  getSyncStatus: (accountId) => request('GET', `/accounts/${accountId}/sync-status`),

  // Admin
  getDashboard: () => request('GET', '/admin/dashboard'),
  getSettings: () => request('GET', '/admin/settings'),
  updateSetting: (data) => request('PUT', '/admin/settings', data),
  deleteSetting: (key) => request('DELETE', `/admin/settings/${key}`),
  getAdminAccounts: () => request('GET', '/admin/accounts'),
  removeAccount: (accountId) => request('DELETE', `/admin/accounts/${accountId}`),

  // AI
  analyzeEmail: (emailId) => request('POST', `/ai/analyze/${emailId}`),
  analyzeThread: (threadId) => request('POST', `/ai/analyze/thread/${threadId}`),

  // Health
  health: () => request('GET', '/health'),
};
