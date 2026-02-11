import { writable, derived } from 'svelte/store';

// Auth state
export const user = writable(null);
export const isAuthenticated = derived(user, ($user) => $user !== null);

// Navigation
export const currentPage = writable('inbox');
export const currentMailbox = writable('INBOX');
export const selectedEmailId = writable(null);
export const selectedThreadId = writable(null);

// Email state
export const emails = writable([]);
export const emailsLoading = writable(false);
export const emailsTotal = writable(0);
export const currentPageNum = writable(1);

// Accounts
export const accounts = writable([]);
export const selectedAccountId = writable(null);

// UI state
export const sidebarCollapsed = writable(false);
export const composeOpen = writable(false);
export const composeData = writable(null);
export const searchQuery = writable('');
export const toastMessage = writable(null);

// Show toast notification
export function showToast(message, type = 'info', duration = 3000) {
  toastMessage.set({ message, type, duration });
  setTimeout(() => {
    toastMessage.set(null);
  }, duration);
}
