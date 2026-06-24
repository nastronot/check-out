import { describe, expect, it } from 'vitest';
import { aliveFromStatus } from '../lib/stores';
import type { Status } from '../lib/types';

const S = (over: Partial<Status>): Status => ({
  alive: true,
  mode: 'clock',
  top: '',
  bottom: '',
  brightness: 3,
  blank: false,
  scroll: false,
  last_command_id: null,
  updated_at: '2026-06-23T12:00:00+00:00',
  ...over,
});

describe('aliveFromStatus (alive derived from status freshness)', () => {
  const now = Date.parse('2026-06-23T12:00:00+00:00');

  it('is alive when marked alive and fresh (< 5s old)', () => {
    expect(aliveFromStatus(S({}), now + 1000)).toBe(true);
  });

  it('is offline when the status is stale (>= 5s old)', () => {
    expect(aliveFromStatus(S({}), now + 6000)).toBe(false);
  });

  it('is offline when not marked alive, even if fresh', () => {
    expect(aliveFromStatus(S({ alive: false }), now)).toBe(false);
  });

  it('is offline for missing / unparseable status', () => {
    expect(aliveFromStatus(null, now)).toBe(false);
    expect(aliveFromStatus(S({ updated_at: null }), now)).toBe(false);
    expect(aliveFromStatus(S({ updated_at: 'not-a-date' }), now)).toBe(false);
  });
});
