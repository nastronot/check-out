import { describe, expect, it } from 'vitest';
import {
  actionLabel,
  FLASH_MS,
  groupActions,
  isFlashing,
  isNewPress,
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
  // The flash starts when the PAGE sees a new press, not at the press time:
  // the 500 ms poll can arrive after a 400 ms window measured from the press.
  it('is on for FLASH_MS after the page saw the press, then off', () => {
    expect(isFlashing(1000, 1010)).toBe(true);
    expect(isFlashing(1000, 1000 + FLASH_MS + 1)).toBe(false);
    expect(isFlashing(null, 1000)).toBe(false);
  });
});

describe('isNewPress', () => {
  it('is true only when the press stamp changes to a real value', () => {
    expect(isNewPress(null, '2026-09-28T12:00:00Z')).toBe(true);
    expect(isNewPress('2026-09-28T12:00:00Z', '2026-09-28T12:00:00Z')).toBe(false);
    expect(isNewPress('2026-09-28T12:00:00Z', '2026-09-28T12:00:01Z')).toBe(true);
    expect(isNewPress('2026-09-28T12:00:00Z', null)).toBe(false);
  });
});
