import { describe, expect, it } from 'vitest';
import {
  actionLabel,
  FLASH_MS,
  groupActions,
  isFlashing,
  routeFromHash,
  showBumpbarNav,
  type BumpAction,
} from '../lib/bumpbar';

const acts: BumpAction[] = [
  { id: 'none', label: 'nothing', group: 'checkout', hint: '', repeat: false },
  { id: 'lock', label: 'lock screen', group: 'system', hint: '', repeat: false },
  { id: 'mode_next', label: 'next mode', group: 'checkout', hint: '', repeat: false },
];

describe('routeFromHash', () => {
  it('maps #/bumpbar to the bump bar page, anything else to the board', () => {
    expect(routeFromHash('#/bumpbar')).toBe('bumpbar');
    expect(routeFromHash('')).toBe('board');
    expect(routeFromHash('#/')).toBe('board');
    expect(routeFromHash('#/nope')).toBe('board');
  });
});

describe('showBumpbarNav', () => {
  it('hides the link on a machine whose service never ran', () => {
    expect(showBumpbarNav(false, 'board')).toBe(false);
    expect(showBumpbarNav(true, 'board')).toBe(true);
    expect(showBumpbarNav(false, 'bumpbar')).toBe(true);
  });
});

describe('groupActions', () => {
  it('splits check-out and system, keeping catalogue order', () => {
    const g = groupActions(acts);
    expect(g.checkout.map((a) => a.id)).toEqual(['none', 'mode_next']);
    expect(g.system.map((a) => a.id)).toEqual(['lock']);
  });
});

describe('actionLabel', () => {
  it('uses the catalogue label and falls back to the id', () => {
    expect(actionLabel(acts, 'lock')).toBe('lock screen');
    expect(actionLabel(acts, 'gone')).toBe('gone');
  });
});

describe('isFlashing', () => {
  const at = '2026-09-28T12:00:00+00:00';
  const t = Date.parse(at);
  it('is on for FLASH_MS after a press, then off', () => {
    expect(isFlashing(at, t + 10)).toBe(true);
    expect(isFlashing(at, t + FLASH_MS + 1)).toBe(false);
    expect(isFlashing(null, t)).toBe(false);
    expect(isFlashing('garbage', t)).toBe(false);
  });
});
