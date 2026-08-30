export const DEFAULT_AUTHENTICATED_PAGE = 'flow';

const lazyRouteDefinitions = Object.freeze({
  flow: Object.freeze({ label: 'Flow', load: () => import('../pages/Flow.svelte') }),
  inbox: Object.freeze({ label: 'Email', load: () => import('../pages/Inbox.svelte') }),
  calendar: Object.freeze({ label: 'Calendar', load: () => import('../pages/Calendar.svelte') }),
  compose: Object.freeze({ label: 'Compose', load: () => import('../pages/Compose.svelte') }),
  stats: Object.freeze({ label: 'Stats', load: () => import('../pages/Stats.svelte') }),
  'ai-insights': Object.freeze({ label: 'AI Insights', load: () => import('../pages/AIInsights.svelte') }),
  todos: Object.freeze({ label: 'Todos', load: () => import('../pages/Todos.svelte') }),
  chat: Object.freeze({ label: 'Chat', load: () => import('../pages/Chat.svelte') }),
  subscriptions: Object.freeze({ label: 'Subscriptions', load: () => import('../pages/Subscriptions.svelte') }),
  admin: Object.freeze({ label: 'Settings', load: () => import('../pages/Admin.svelte') }),
  'standalone-email': Object.freeze({
    label: 'Message',
    load: () => import('../pages/EmailViewStandalone.svelte'),
  }),
});

export const AUTHENTICATED_PAGES = Object.freeze(
  Object.keys(lazyRouteDefinitions).filter(key => key !== 'standalone-email'),
);

const authenticatedPageSet = new Set(AUTHENTICATED_PAGES);

export function normalizeAuthenticatedPage(page) {
  return typeof page === 'string' && authenticatedPageSet.has(page)
    ? page
    : DEFAULT_AUTHENTICATED_PAGE;
}

export function getLazyRouteLabel(key) {
  return lazyRouteDefinitions[key]?.label || 'This screen';
}

function componentFromModule(module, key) {
  if (!module?.default) {
    throw new Error(`Lazy route "${key}" did not provide a default component export.`);
  }
  return module.default;
}

/**
 * A small, independently testable cache around the route import functions.
 * Concurrent requests share one promise, successful components remain warm,
 * and a rejected import is removed immediately so a later retry can recover.
 */
export function createLazyRouteCache(definitions) {
  const pending = new Map();
  const resolved = new Map();

  function peek(key) {
    return resolved.get(key) || null;
  }

  function clear(key) {
    pending.delete(key);
    resolved.delete(key);
  }

  function load(key, { retry = false } = {}) {
    const definition = definitions[key];
    if (!definition) return Promise.reject(new Error(`Unknown lazy route: ${key}`));

    if (retry) clear(key);
    if (resolved.has(key)) return Promise.resolve(resolved.get(key));
    if (pending.has(key)) return pending.get(key);

    let request;
    request = Promise.resolve()
      .then(() => definition.load())
      .then(module => {
        const component = componentFromModule(module, key);
        // A retry may supersede an older request before that request settles.
        // Only the promise still registered as current may populate the cache.
        if (pending.get(key) === request) {
          resolved.set(key, component);
          pending.delete(key);
        }
        return component;
      })
      .catch(error => {
        if (pending.get(key) === request) pending.delete(key);
        throw error;
      });
    pending.set(key, request);
    return request;
  }

  return Object.freeze({ clear, load, peek });
}

const appRouteCache = createLazyRouteCache(lazyRouteDefinitions);

export function getCachedLazyRoute(key) {
  return appRouteCache.peek(key);
}

export function loadLazyRoute(key, options) {
  return appRouteCache.load(key, options);
}

export function preloadAuthenticatedPage(page) {
  const key = normalizeAuthenticatedPage(page);
  return loadLazyRoute(key).catch(() => null);
}

/**
 * Coordinates route requests so a slow import can never replace a newer
 * navigation. The consumer owns presentation; this object only emits stable
 * idle/loading/ready/error states.
 */
export function createLazyRouteCoordinator({
  load = loadLazyRoute,
  peek = getCachedLazyRoute,
  onState,
} = {}) {
  if (typeof onState !== 'function') {
    throw new TypeError('createLazyRouteCoordinator requires an onState callback.');
  }

  let generation = 0;

  function emit(state) {
    onState(Object.freeze(state));
  }

  async function open(key, { retry = false } = {}) {
    const requestGeneration = ++generation;
    const cached = retry ? null : peek(key);

    if (cached) {
      emit({ key, status: 'ready', component: cached, error: null });
      return 'ready';
    }

    emit({ key, status: 'loading', component: null, error: null });
    try {
      const component = await load(key, { retry });
      if (requestGeneration !== generation) return 'stale';
      emit({ key, status: 'ready', component, error: null });
      return 'ready';
    } catch (error) {
      if (requestGeneration !== generation) return 'stale';
      emit({ key, status: 'error', component: null, error });
      return 'error';
    }
  }

  function cancel({ reset = true } = {}) {
    generation += 1;
    if (reset) emit({ key: null, status: 'idle', component: null, error: null });
  }

  return Object.freeze({ cancel, open });
}
