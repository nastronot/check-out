// Thin fetch wrappers over the FastAPI control surface. Same-origin /api/* in
// production; proxied to :8000 by vite in dev.

import type {
  AppState,
  CommandRef,
  Health,
  Library,
  LibraryGlyph,
  LibraryMessage,
  Status,
} from './types';

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

// --- library (saved messages + glyphs) ------------------------------------
export const getLibrary = () => req<Library>('/api/library');

export const saveMessage = (item: Partial<LibraryMessage>) =>
  req<LibraryMessage>('/api/library/messages', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(item),
  });

export const deleteMessage = (id: string) =>
  req<{ ok: boolean }>(`/api/library/messages/${id}`, { method: 'DELETE' });

/** Recall a saved message onto the live state; returns the new state. */
export const recallMessage = (id: string) =>
  req<AppState>(`/api/library/messages/${id}/recall`, { method: 'POST' });

export const saveGlyph = (name: string, rows: number[]) =>
  req<LibraryGlyph>('/api/library/glyphs', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ name, rows }),
  });

export const deleteGlyph = (id: string) =>
  req<{ ok: boolean }>(`/api/library/glyphs/${id}`, { method: 'DELETE' });

/** Persist a new glyph order (drag-to-reorder); returns the reordered glyphs. */
export const reorderGlyphs = (ids: string[]) =>
  req<{ glyphs: LibraryGlyph[] }>('/api/library/glyphs/order', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ ids }),
  });
