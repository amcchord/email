function componentFromModule(module) {
  if (!module?.default) {
    throw new Error('The rich editor module did not provide a default component export.');
  }
  return module.default;
}

/**
 * Deduplicate the editor import and keep only the newest retry authoritative.
 * The loader is injectable so the cache and overlap rules remain unit-testable.
 */
export function createLazyEditorCache(
  loadModule = () => import('../components/email/RichEditor.svelte'),
) {
  let pending = null;
  let resolved = null;

  function peek() {
    return resolved;
  }

  function clear() {
    pending = null;
    resolved = null;
  }

  function load({ retry = false } = {}) {
    if (retry) clear();
    if (resolved) return Promise.resolve(resolved);
    if (pending) return pending;

    let request;
    request = Promise.resolve()
      .then(() => loadModule())
      .then(module => {
        const component = componentFromModule(module);
        if (pending === request) {
          resolved = component;
          pending = null;
        }
        return component;
      })
      .catch(error => {
        if (pending === request) pending = null;
        throw error;
      });
    pending = request;
    return request;
  }

  return Object.freeze({ clear, load, peek });
}

const editorCache = createLazyEditorCache();

export function getCachedRichEditor() {
  return editorCache.peek();
}

export function loadRichEditor(options) {
  return editorCache.load(options);
}
