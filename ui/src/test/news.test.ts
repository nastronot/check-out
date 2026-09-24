import { describe, expect, it } from 'vitest';
import { newsSummary } from '../lib/news';

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
    expect(newsSummary({ sources: {}, latest: null, error: null, alerting: false }, 0)).toMatch(/no sources/i);
  });
});
