import { describe, expect, it } from 'vitest';
import { ago, feedRows, newsSummary } from '../lib/news';

const src = (title: string | null, error: string | null = null) => ({
  title,
  published: '2026-09-24T05:59:15+00:00',
  error,
});

describe('newsSummary', () => {
  it('waits when nothing has been fetched', () => {
    expect(newsSummary(null)).toMatch(/waiting/i);
    expect(newsSummary({ sources: {}, latest: null, error: null, alerting: false })).toMatch(/waiting/i);
  });
  it('shows the newest headline with its source', () => {
    const s = newsSummary({
      sources: { nyt: src('Court blocks ban') },
      latest: { source: 'nyt', title: 'Court blocks ban', published: '2026-09-24T05:59:15+00:00' },
      error: null,
      alerting: false,
    });
    expect(s).toMatch(/^NYT · Court blocks ban/);
  });
  it('names a failing source', () => {
    const s = newsSummary({
      sources: { bbc: src('Lead', 'OSError: timed out'), nyt: src('Other') },
      latest: { source: 'bbc', title: 'Lead', published: null },
      error: null,
      alerting: false,
    });
    expect(s).toMatch(/BBC failed/);
  });
  it('says when every source failed', () => {
    expect(newsSummary({ sources: {}, latest: null, error: 'OSError: every source failed', alerting: false }))
      .toMatch(/^Fetch failed/);
  });
});

describe('newsSummary review fixes', () => {
  it('includes the time of the newest headline', () => {
    const s = newsSummary({
      sources: { nyt: src('Court blocks ban') },
      latest: { source: 'nyt', title: 'Court blocks ban', published: '2026-09-24T05:59:15+00:00' },
      error: null,
      alerting: false,
    });
    expect(s).toMatch(/^NYT · Court blocks ban · \d{1,2}:\d{2}/);
  });
  it('says so when no sources are selected', () => {
    expect(newsSummary({ sources: {}, latest: null, error: null, alerting: false }, 0)).toMatch(/no topics/i);
  });
});

describe('ago', () => {
  const now = Date.parse('2026-11-08T06:00:00Z');
  it('counts minutes, then hours, then days', () => {
    expect(ago('2026-11-08T05:59:40Z', now)).toBe('now');
    expect(ago('2026-11-08T05:48:00Z', now)).toBe('12m');
    expect(ago('2026-11-08T03:00:00Z', now)).toBe('3h');
    expect(ago('2026-11-05T06:00:00Z', now)).toBe('3d');
    expect(ago(null, now)).toBe('');
  });
});

describe('feedRows', () => {
  const catalogue = {
    tech: [{ key: 'ars', name: 'ARS' }],
    politics: [{ key: 'politico', name: 'POLITICO' }, { key: 'pbs_politics', name: 'PBS' }],
    mississippi: [{ key: 'mt', name: 'MT' }],
  };
  const now = Date.parse('2026-11-08T06:00:00Z');
  const status = {
    sources: {
      politico: { name: 'POLITICO', title: 'GOP reckoning', link: 'https://politico.com/x',
                  published: '2026-11-08T05:00:00Z', error: null },
      pbs_politics: { name: 'PBS', title: null, link: null, published: null, error: 'OSError: timed out' },
    },
    latest: null, error: null, alerting: false,
  };
  it('lists every topic in catalogue order, unticked ones off', () => {
    const rows = feedRows(catalogue, status, ['politics'], now);
    expect(rows.map((r) => [r.topic, r.on])).toEqual([['tech', false], ['politics', true], ['mississippi', false]]);
    expect(rows[0].feeds[0]).toMatchObject({ name: 'ARS', state: 'off', title: null });
  });
  it('shows each ticked feed\'s lead with its link and age, or its error', () => {
    const [, politics] = feedRows(catalogue, status, ['politics'], now);
    expect(politics.feeds[0]).toMatchObject({ state: 'ok', title: 'GOP reckoning', link: 'https://politico.com/x', age: '1h' });
    expect(politics.feeds[1]).toMatchObject({ state: 'error', error: 'OSError: timed out' });
  });
  it('waits for a ticked feed not fetched yet, and for no catalogue shows nothing', () => {
    expect(feedRows(catalogue, null, ['tech'], now)[0].feeds[0].state).toBe('waiting');
    expect(feedRows(null, status, ['tech'], now)).toEqual([]);
  });
});
