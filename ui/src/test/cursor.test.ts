import { describe, expect, it } from 'vitest';
import { lineToCells } from '../lib/font5x7';
import { withCursor } from '../lib/cursor';

const lit = (cell: boolean[][]) => cell.flat().filter(Boolean).length;

describe('withCursor', () => {
  const top = lineToCells('09/23/26 WED 08:33', {});
  const bottom = lineToCells('', {});

  it('lights the whole cell under the cursor', () => {
    const [t, b] = withCursor(top, bottom, 10);
    expect(lit(t[10])).toBe(35);
    expect(t[9]).toBe(top[9]);
    expect(b).toEqual(bottom);
  });

  it('reaches the bottom line', () => {
    const [, b] = withCursor(top, bottom, 25);
    expect(lit(b[5])).toBe(35);
  });

  it('does nothing without a cursor and never mutates its input', () => {
    expect(withCursor(top, bottom, null)).toEqual([top, bottom]);
    withCursor(top, bottom, 10);
    expect(lit(top[10])).toBeLessThan(35);
  });
});
