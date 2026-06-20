import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  deleteGlyph,
  getLibrary,
  recallMessage,
  saveGlyph,
  saveMessage,
} from '../lib/api';
import { normGlyph } from '../lib/glyphedit';

interface FetchCall {
  url: string;
  init: RequestInit | undefined;
}
const calls: FetchCall[] = [];

function mockFetch(status: number, body: unknown): void {
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    };
  }) as unknown as typeof fetch;
}

afterEach(() => {
  calls.length = 0;
  vi.restoreAllMocks();
});

describe('library api', () => {
  it('GET /api/library returns the library', async () => {
    const lib = { messages: [], glyphs: [] };
    mockFetch(200, lib);
    expect(await getLibrary()).toEqual(lib);
    expect(calls[0].url).toBe('/api/library');
  });

  it('saveMessage POSTs the composable state', async () => {
    mockFetch(200, { id: 'a', name: 'Hi' });
    await saveMessage({ name: 'Hi', message: 'X', glyphs: {} });
    expect(calls[0].url).toBe('/api/library/messages');
    expect(calls[0].init?.method).toBe('POST');
    expect(JSON.parse(String(calls[0].init?.body)).name).toBe('Hi');
  });

  it('recallMessage POSTs to the recall endpoint and returns state', async () => {
    const state = { mode: 'message', message: 'TEMP {g0}C' };
    mockFetch(200, state);
    expect(await recallMessage('abc')).toEqual(state);
    expect(calls[0].url).toBe('/api/library/messages/abc/recall');
    expect(calls[0].init?.method).toBe('POST');
  });

  it('saveGlyph + deleteGlyph hit the right routes', async () => {
    mockFetch(200, { id: 'g1', name: 'heart', rows: [0, 10, 31, 31, 14, 4, 0] });
    await saveGlyph('heart', [0, 10, 31, 31, 14, 4, 0]);
    expect(calls[0].url).toBe('/api/library/glyphs');

    mockFetch(200, { ok: true });
    await deleteGlyph('g1');
    expect(calls.at(-1)?.url).toBe('/api/library/glyphs/g1');
    expect(calls.at(-1)?.init?.method).toBe('DELETE');
  });

  it('a library glyph loads into a slot as a normalized 7-row glyph', () => {
    // load-into-slot path: rows are normalized to 7 low-5-bit ints.
    expect(normGlyph([0xff, 0, 0, 0, 0, 0, 0])).toEqual([31, 0, 0, 0, 0, 0, 0]);
    expect(normGlyph([1, 2, 3]).length).toBe(7); // wrong length -> empty 7-row
  });
});
