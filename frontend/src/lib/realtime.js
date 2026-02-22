/**
 * Real-time event stream using Server-Sent Events.
 *
 * Connects to /api/events/stream and exposes a Svelte store that
 * pages can react to for automatic data refreshes.
 */

import { writable } from 'svelte/store';

export const lastEvent = writable(null);

let eventSource = null;
let reconnectTimer = null;
let reconnectDelay = 1000;

const MAX_RECONNECT_DELAY = 30000;
const SSE_URL = '/api/events/stream';

function handleEvent(eventType) {
  return function (e) {
    let data = {};
    try {
      data = JSON.parse(e.data);
    } catch {
      // ignore parse errors
    }
    lastEvent.set({ type: eventType, ...data });
  };
}

function connect() {
  if (eventSource) {
    return;
  }

  eventSource = new EventSource(SSE_URL, { withCredentials: true });

  eventSource.addEventListener('new_emails', handleEvent('new_emails'));
  eventSource.addEventListener('emails_updated', handleEvent('emails_updated'));
  eventSource.addEventListener('sync_complete', handleEvent('sync_complete'));

  eventSource.onopen = function () {
    reconnectDelay = 1000;
  };

  eventSource.onerror = function () {
    cleanup();
    scheduleReconnect();
  };
}

function cleanup() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function scheduleReconnect() {
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(function () {
    reconnectTimer = null;
    connect();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
}

export function startRealtime() {
  connect();
}

export function stopRealtime() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  cleanup();
  reconnectDelay = 1000;
}
