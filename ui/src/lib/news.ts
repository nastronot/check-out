import type { NewsStatus } from './types';

const LABEL: Record<string, string> = { ap: 'AP', bbc: 'BBC', nyt: 'NYT' };
const label = (key: string) => LABEL[key] ?? key.toUpperCase();

/** One line for the News section: the newest headline, or what went wrong. */
export function newsSummary(n: NewsStatus | null | undefined): string {
  if (n?.error && !n.latest) return `Fetch failed: ${n.error}`;
  if (!n?.latest) return 'Waiting for the first headlines…';
  const failed = Object.entries(n.sources)
    .filter(([, s]) => s.error)
    .map(([k]) => label(k));
  const tail = failed.length ? ` · ${failed.join(', ')} failed` : '';
  return `${label(n.latest.source)} · ${n.latest.title}${tail}`;
}
