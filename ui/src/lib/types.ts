// Mirrors checkout/state.py — keep in sync with the daemon's schema.

export type Mode = 'clock' | 'message' | 'scroll' | 'marquee' | 'spectrum';
/** Spectrum audio source: the mic, or a PipeWire/Pulse monitor of playback. */
export type AudioSource = 'mic' | 'system';
/** Brightness is a discrete level index 0..3 (0 Min, 1 Med, 2 Med+, 3 Max). */
export type Brightness = 0 | 1 | 2 | 3;
export type Animation = 'none' | 'flash' | 'blink' | 'pulse';
export type Align = 'left' | 'center' | 'right';
export type ScrollDir = 'left' | 'right';
/** Marquee bottom is static-only (a live clock there stops the hardware scroll). */
export type MarqueeBottom = 'static';
/**
 * Per-row content source for software SCROLL mode. EXTENSION POINT: add 'news'
 * here (and a daemon renderer) for a live news row — the UI selector already has
 * room for a third option.
 */
export type ScrollSource = 'message' | 'clock';

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
  // marquee (hardware ticker — top autonomous, FIXED speed)
  marquee_text: string;
  marquee_bottom: MarqueeBottom;
  marquee_bottom_text: string;
  // software scroll (mode "scroll") — per-row content source + scroll + direction
  scroll_top_source: ScrollSource;
  scroll_bottom_source: ScrollSource;
  scroll_top: boolean;
  scroll_bottom: boolean;
  scroll_dir_top: ScrollDir;
  scroll_dir_bottom: ScrollDir;
  brightness: Brightness;
  blank: boolean;
  scroll: boolean;
  code_page: number;
  scroll_speed_ms: number;
  animation: Animation;
  animation_params: { on_ms: number; off_ms: number; step_ms: number };
  glyphs: Record<string, number[]>;
  // spectrum analyzer settings (the live bar data goes over a socket, not here)
  audio_source: AudioSource;
  audio_device: string | number | null;
  audio_gain: number;
  audio_decay: number;
  command: CommandRef;
  updated_at?: string;
}

/** An audio input device from devices.json (the spectrum SOURCE selector). */
export interface AudioDevice {
  index: number;
  name: string;
  max_input_channels: number;
  is_monitor: boolean;
  default_samplerate?: number;
}

export interface Status {
  alive: boolean;
  mode: string;
  top: string;
  bottom: string;
  brightness: Brightness;
  blank: boolean;
  scroll: boolean;
  /** Spectrum mode: the 20 bar heights (0..14) the daemon last rendered, else null. */
  bars: number[] | null;
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
  mode: 'message' | 'scroll';
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
