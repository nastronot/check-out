import { describe, expect, it } from 'vitest';
import { weatherSummary } from '../lib/weather';

const base = {
  high: 92.6, low: 74.2, current: 82.4, rain: 82,
  observed_at: '2026-09-24T01:45:00+00:00',
  fetched_at: '2026-09-24T01:46:00+00:00',
  error: null,
};

describe('weatherSummary', () => {
  it('waits when there is nothing yet', () => {
    expect(weatherSummary(null)).toMatch(/waiting/i);
    expect(weatherSummary({ ...base, observed_at: null, fetched_at: null })).toMatch(/waiting/i);
  });
  it('reports the reading time', () => {
    expect(weatherSummary(base)).toMatch(/^Reading from /);
  });
  it('leads with the error when a fetch failed', () => {
    expect(weatherSummary({ ...base, error: 'OSError: down' })).toMatch(/^Last fetch failed: OSError: down/);
  });
});
