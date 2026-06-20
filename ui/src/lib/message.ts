// Message helpers. The display is 2 lines x 20 chars; in message mode a '\n'
// splits top/bottom (the daemon's MessageFrame partitions on the first newline),
// so the real limit is 20 PER LINE, not 40 total.

export const LINE_WIDTH = 20;

export interface LineBudget {
  /** Does the message contain a newline (i.e. an explicit top/bottom split)? */
  hasNewline: boolean;
  /** Char count of line 1 (everything before the first '\n', else the whole msg). */
  top: number;
  /** Char count of line 2 (everything after the first '\n'); 0 when no newline. */
  bottom: number;
  topOver: boolean;
  bottomOver: boolean;
}

/** Per-line character budget for a message, mirroring MessageFrame's split. */
export function lineBudget(message: string): LineBudget {
  const nl = message.indexOf('\n');
  const hasNewline = nl >= 0;
  const top = hasNewline ? nl : message.length;
  const bottom = hasNewline ? message.length - nl - 1 : 0;
  return {
    hasNewline,
    top,
    bottom,
    topOver: top > LINE_WIDTH,
    bottomOver: bottom > LINE_WIDTH,
  };
}
