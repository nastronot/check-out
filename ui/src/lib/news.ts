import type { NewsCatalogue, NewsStatus, NewsTopic } from './types';

// The outlet name comes from status (news.SOURCES); the key is the fallback.
const label = (n: NewsStatus, key: string) => n.sources[key]?.name ?? key.toUpperCase();

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** One line for the News section: the newest headline (source · title · time),
 *  or what went wrong. `selected` is how many topics are ticked. */
export function newsSummary(n: NewsStatus | null | undefined, selected?: number): string {
  if (selected === 0) return 'No topics selected.';
  if (n?.error && !n.latest) return `Fetch failed: ${n.error}`;
  if (!n?.latest) return 'Waiting for the first headlines…';
  const failed = Object.entries(n.sources)
    .filter(([, s]) => s.error)
    .map(([k]) => label(n, k));
  const tail = failed.length ? ` · ${failed.join(', ')} failed` : '';
  const when = n.latest.published ? ` · ${time(n.latest.published)}` : '';
  const name = n.latest.name ?? label(n, n.latest.source);
  return `${name} · ${n.latest.title}${when}${tail}`;
}

/** "now", "12m", "3h", "2d" — how long ago `iso` was, from `now` (ms). */
export function ago(iso: string | null, now: number): string {
  if (!iso) return '';
  const min = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000));
  if (min < 1) return 'now';
  if (min < 60) return `${min}m`;
  if (min < 48 * 60) return `${Math.floor(min / 60)}h`;
  return `${Math.floor(min / 1440)}d`;
}

/** The link if it is a real http(s) URL, else null. The daemon already filters
 *  (news.safe_link); this second check means a `javascript:` link can never
 *  become an href, whatever writes status.json. */
export function safeLink(u: string | null | undefined): string | null {
  if (!u) return null;
  try {
    const p = new URL(u);
    return p.protocol === 'http:' || p.protocol === 'https:' ? p.href : null;
  } catch {
    return null;
  }
}

/** One feed in the Feeds list. `off`: its topic isn't ticked, so the daemon
 *  doesn't fetch it; `waiting`: ticked, no reply yet. */
export interface FeedRow {
  key: string;
  name: string;
  state: 'off' | 'waiting' | 'ok' | 'error';
  title: string | null;
  link: string | null;
  age: string;
  error: string | null;
}

/** Every topic's feeds with their current lead story, in catalogue order. */
export function feedRows(
  catalogue: NewsCatalogue | null,
  n: NewsStatus | null | undefined,
  topics: NewsTopic[],
  now: number,
): { topic: NewsTopic; on: boolean; feeds: FeedRow[] }[] {
  if (!catalogue) return [];
  return (Object.keys(catalogue) as NewsTopic[]).map((topic) => {
    const on = topics.includes(topic);
    const feeds = catalogue[topic].map(({ key, name }): FeedRow => {
      const s = on ? n?.sources[key] : undefined;
      const title = s?.title ?? null;
      const state = !on ? 'off' : !s ? 'waiting' : title ? 'ok' : s.error ? 'error' : 'waiting';
      return {
        key,
        name,
        state,
        title,
        link: safeLink(s?.link),
        age: ago(s?.published ?? null, now),
        error: s?.error ?? null,
      };
    });
    return { topic, on, feeds };
  });
}
