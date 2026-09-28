import { describe, expect, it } from 'vitest';
import { displayLabel, IBM_LABEL } from '../lib/display';

describe('displayLabel', () => {
  it('uses the daemon-reported label', () => {
    expect(displayLabel({ display_label: 'HP LD220 2×20 VFD' } as never)).toBe('HP LD220 2×20 VFD');
  });
  it('falls back to the IBM label for an older daemon or no status', () => {
    expect(displayLabel(null)).toBe(IBM_LABEL);
    expect(displayLabel({ display_label: null } as never)).toBe(IBM_LABEL);
    expect(IBM_LABEL).toBe('IBM SUREPOS 2×20 VFD');
  });
});
