// Thin fetch wrappers over the FastAPI control surface. Same-origin /api/* in
// production; proxied to :8000 by vite in dev.

import type { AppState, CommandRef, Health, Status } from './types';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${url} → ${res.status}`);
  }
  return (await res.json()) as T;
}

export const getStatus = () => req<Status>('/api/status');
export const getState = () => req<AppState>('/api/state');
export const getHealth = () => req<Health>('/api/health');

/** Merge-patch a partial desired state; returns the full persisted state. */
export const putState = (patch: Partial<AppState>) =>
  req<AppState>('/api/state', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(patch),
  });

/** Queue a one-shot daemon command (self_test | reset | redefine_glyphs). */
export const postCommand = (action: string, args: Record<string, unknown> = {}) =>
  req<{ command: CommandRef }>('/api/command', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ action, args }),
  });
