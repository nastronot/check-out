import type { NewsStatus } from './types';

// Same labels as checkout/news.py SOURCES (they also prefix the ticker).
const LABEL: Record<string, string> = {
  ap: 'AP', bbc: 'BBC', nyt: 'NYT', mt: 'MT', wired: 'WIRED', hill: 'HILL', ai: 'AI', linux: 'LINUX',
};
const label = (key: string) => LABEL[key] ?? key.toUpperCase();

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** One line for the News section: the newest headline (source · title · time),
 *  or what went wrong. `selected` is how many sources are ticked. */
export function newsSummary(n: NewsStatus | null | undefined, selected?: number): string {
  if (selected === 0) return 'No sources selected.';
  if (n?.error && !n.latest) return `Fetch failed: ${n.error}`;
  if (!n?.latest) return 'Waiting for the first headlines…';
  const failed = Object.entries(n.sources)
    .filter(([, s]) => s.error)
    .map(([k]) => label(k));
  const tail = failed.length ? ` · ${failed.join(', ')} failed` : '';
  const when = n.latest.published ? ` · ${time(n.latest.published)}` : '';
  return `${label(n.latest.source)} · ${n.latest.title}${when}${tail}`;
}
