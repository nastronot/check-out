import { describe, expect, it } from 'vitest';
import { LINE_WIDTH, lineBudget } from '../lib/message';

describe('message line budget', () => {
  it('counts a single line toward 20 when there is no newline', () => {
    const b = lineBudget('HELLO');
    expect(b.hasNewline).toBe(false);
    expect(b.top).toBe(5);
    expect(b.bottom).toBe(0);
    expect(b.topOver).toBe(false);
  });

  it('splits top/bottom on the first newline (no stripping)', () => {
    const b = lineBudget('HELLO\nWORLD!');
    expect(b.hasNewline).toBe(true);
    expect(b.top).toBe(5); // "HELLO"
    expect(b.bottom).toBe(6); // "WORLD!"
  });

  it('treats everything after the first newline as line 2', () => {
    const b = lineBudget('A\nB\nC'); // MessageFrame partitions on the FIRST '\n'
    expect(b.top).toBe(1);
    expect(b.bottom).toBe(3); // "B\nC"
  });

  it('flags a line over the 20-char limit', () => {
    const b = lineBudget('X'.repeat(25));
    expect(LINE_WIDTH).toBe(20);
    expect(b.top).toBe(25);
    expect(b.topOver).toBe(true);
    const b2 = lineBudget('ok\n' + 'Y'.repeat(21));
    expect(b2.bottomOver).toBe(true);
    expect(b2.topOver).toBe(false);
  });

  it('an empty message is zero/zero, no newline', () => {
    expect(lineBudget('')).toMatchObject({ hasNewline: false, top: 0, bottom: 0 });
  });
});
