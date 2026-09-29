// Bump bar page: types for /api/bumpbar and the pure helpers the page uses.

export type BumpGroup = 'checkout' | 'system';
export type Layer = 'tap' | 'shift';

export interface BumpAction {
  id: string;
  label: string;
  group: BumpGroup;
  hint: string;
  repeat: boolean;
}

export interface BumpButton {
  id: string;
  legend: string;
  color: 'red' | 'green' | 'grey' | 'blue' | 'dark';
}

export type BumpMap = Record<Layer, Record<string, string>>;

export interface BumpPress {
  button: string;
  layer: Layer;
  action: string;
  at: string;
}

export interface BumpStatus {
  alive: boolean;
  connected: boolean;
  device: string | null;
  layer: Layer;
  last_press: BumpPress | null;
  error: string | null;
  updated_at: string;
}

export interface BumpBar {
  installed: boolean;
  alive: boolean;
  status: BumpStatus | null;
  map: BumpMap;
  map_error: string | null;
  defaults: BumpMap;
  actions: BumpAction[];
  buttons: BumpButton[];
  shift: string;
  layers: Layer[];
}

export type Route = 'board' | 'bumpbar';

/** Hash routing, no router: `#/bumpbar` is the bump bar page, the rest the board. */
export function routeFromHash(hash: string): Route {
  return hash === '#/bumpbar' ? 'bumpbar' : 'board';
}

/** The masthead link shows where a bump bar service has run (dad), never on a
 *  machine without a bar (work) — unless you are already on the page. */
export function showBumpbarNav(installed: boolean, route: Route): boolean {
  return installed || route === 'bumpbar';
}

export function groupActions(actions: BumpAction[]): Record<BumpGroup, BumpAction[]> {
  return {
    checkout: actions.filter((a) => a.group === 'checkout'),
    system: actions.filter((a) => a.group === 'system'),
  };
}

export function actionLabel(actions: BumpAction[], id: string): string {
  return actions.find((a) => a.id === id)?.label ?? id;
}

/** How long a key on the drawing lights after the real key is pressed. */
export const FLASH_MS = 400;

export function isFlashing(at: string | null | undefined, now = Date.now()): boolean {
  if (!at) return false;
  const t = Date.parse(at);
  if (Number.isNaN(t)) return false;
  return now - t >= 0 && now - t <= FLASH_MS;
}
