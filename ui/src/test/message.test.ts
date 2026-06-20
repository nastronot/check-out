import { describe, expect, it } from 'vitest';
import { LINE_WIDTH, lineBudget, renderedText } from '../lib/message';

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

  it('counts a {gN} glyph placeholder as ONE cell, not 4 chars', () => {
    expect(renderedText('{g0}{g1}{g2}').length).toBe(3);
    const b = lineBudget('{g0}{g1}{g2}');
    expect(b.top).toBe(3); // not 12
    expect(b.topOver).toBe(false);
  });

  it('mixes glyphs and text by rendered cells', () => {
    // "AB" + 2 glyph cells = 4 cells.
    expect(lineBudget('AB{g0}{g7}').top).toBe(4);
  });

  it('per-line glyph counts split on the newline', () => {
    const b = lineBudget('{g0}{g1}\n{g2}{g3}{g4}');
    expect(b.hasNewline).toBe(true);
    expect(b.top).toBe(2);
    expect(b.bottom).toBe(3);
  });

  it('20 glyph cells fit; 21 flags over', () => {
    expect(lineBudget('{g0}'.repeat(20)).topOver).toBe(false);
    expect(lineBudget('{g0}'.repeat(20)).top).toBe(20);
    expect(lineBudget('{g0}'.repeat(21)).topOver).toBe(true);
    expect(lineBudget('{g0}'.repeat(21)).top).toBe(21);
  });
});
