import type { Status } from './types';

export const IBM_LABEL = 'IBM · SUREPOS 500';

/** The attached display's name, as the daemon reports it (IBM before v1.8.0). */
export function displayLabel(status: Status | null | undefined): string {
  return status?.display_label || IBM_LABEL;
}
