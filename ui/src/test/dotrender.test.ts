import { describe, expect, it } from 'vitest';
import { intensityForLevel } from '../lib/dotrender';

describe('brightness -> phosphor intensity', () => {
  it('maps the four levels to four DISTINCT intensities', () => {
    const inks = [0, 1, 2, 3].map(intensityForLevel);
    // All four main colors differ, and bloom strictly increases with level.
    const mains = new Set(inks.map((i) => i.main));
    expect(mains.size).toBe(4);
    for (let i = 1; i < inks.length; i++) {
      expect(inks[i].blur).toBeGreaterThan(inks[i - 1].blur);
    }
  });

  it('clamps out-of-range levels to the nearest stop', () => {
    expect(intensityForLevel(-1)).toEqual(intensityForLevel(0));
    expect(intensityForLevel(9)).toEqual(intensityForLevel(3));
    // Fractional rounds to the nearest stop.
    expect(intensityForLevel(2.4)).toEqual(intensityForLevel(2));
  });
});
