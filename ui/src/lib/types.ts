// Mirrors checkout/state.py — keep in sync with the daemon's schema.

export type Mode = 'clock' | 'message' | 'ticker';
/** Brightness is a discrete level index 0..3 (0 Min, 1 Med, 2 Med+, 3 Max). */
export type Brightness = 0 | 1 | 2 | 3;
export type Animation = 'none' | 'flash' | 'blink' | 'pulse';
export type Align = 'left' | 'center' | 'right';

/** {"0".."8"} -> 7 row ints (low 5 bits = columns 1..5). Shared with state.glyphs. */
export type GlyphMap = Record<string, number[]>;

export interface CommandRef {
  id: string | null;
  action: string | null;
  args: Record<string, unknown>;
}

export interface AppState {
  mode: Mode;
  message: string;
  align_top: Align;
  align_bottom: Align;
  brightness: Brightness;
  blank: boolean;
  scroll: boolean;
  code_page: number;
  scroll_speed_ms: number;
  animation: Animation;
  animation_params: { on_ms: number; off_ms: number; step_ms: number };
  glyphs: Record<string, number[]>;
  command: CommandRef;
  updated_at?: string;
}

export interface Status {
  alive: boolean;
  mode: string;
  top: string;
  bottom: string;
  brightness: Brightness;
  blank: boolean;
  scroll: boolean;
  last_command_id: string | null;
  updated_at: string | null;
}

export interface Health {
  ok: boolean;
  daemon_alive: boolean;
}

// --- saved library (web-owned) --------------------------------------------
export interface LibraryMessage {
  id: string;
  name: string;
  message: string;
  mode: 'message' | 'ticker';
  align_top: Align;
  align_bottom: Align;
  brightness: Brightness;
  glyphs: GlyphMap;
}

export interface LibraryGlyph {
  id: string;
  name: string;
  rows: number[];
}

export interface Library {
  messages: LibraryMessage[];
  glyphs: LibraryGlyph[];
}
