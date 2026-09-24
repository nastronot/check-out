import type { WeatherStatus } from './types';

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** One line for the Weather panel: freshness, or what went wrong. */
export function weatherSummary(w: WeatherStatus | null | undefined): string {
  const seen = w?.observed_at ? `showing the ${time(w.observed_at)} reading` : '';
  if (w?.error) return `Last fetch failed: ${w.error}${seen ? ` — ${seen}` : ''}`;
  if (!w?.observed_at) return 'Waiting for the first reading…';
  return `Reading from ${time(w.observed_at)} · refreshes every 15 min`;
}

/** A coordinate typed by the user: a number within ±`limit`, `null` when the
 *  field is empty (location cleared), or `undefined` when it is not valid. */
export function parseCoord(text: string, limit: number): number | null | undefined {
  const t = text.trim();
  if (t === '') return null;
  const v = Number(t);
  return Number.isFinite(v) && Math.abs(v) <= limit ? v : undefined;
}
