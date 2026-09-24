<script lang="ts">
  import { lineBudget } from '../message';
  import { audioDevices, refreshDevices } from '../stores';
  import { parseCoord, weatherSummary } from '../weather';
  import type {
    Align,
    AppState,
    Animation,
    AudioSource,
    Mode,
    ScrollDir,
    ScrollSource,
    SpectrumStyle,
    SpectrumLayout,
    Status,
    DynamicColon,
    DynamicPacmanSprite,
  } from '../types';

  export let state: AppState | null = null;
  export let status: Status | null = null;
  export let patch: (p: Partial<AppState>) => void;

  // 'marquee' is HIDDEN (v1.4.0), not removed: the hardware ticker scrolls only
  // the top row at one fixed speed, which message mode's software scroll does
  // better. Its daemon path and its panel below still work — add it back here to
  // show the button again. ('scroll' merged into 'message' in v1.4.0.)
  const MODES: Mode[] = ['clock', 'message', 'spectrum', 'dynamic'];
  const ANIMATIONS: Animation[] = ['none', 'flash', 'blink', 'pulse'];
  const ALIGNS: Align[] = ['left', 'center', 'right'];

  // Local mirror of the message so typing is smooth; PUTs are debounced.
  let messageDraft = '';
  let lastSeen = '';
  $: if (state && state.message !== lastSeen) {
    lastSeen = state.message;
    messageDraft = state.message;
  }

  let msgTimer: ReturnType<typeof setTimeout> | null = null;
  function onMessageInput(): void {
    if (msgTimer) clearTimeout(msgTimer);
    msgTimer = setTimeout(() => patch({ message: messageDraft }), 250);
  }

  // Per-line budget (20 chars/line; a '\n' splits top/bottom). Never strips '\n'.
  $: budget = lineBudget(messageDraft);

  // Typed handlers. Svelte parses markup expressions with acorn (not TS), so no
  // casts/annotations can live in the template — keep all TS in here.
  function num(e: Event): number {
    return Number((e.target as HTMLInputElement | HTMLSelectElement).value);
  }
  function checked(e: Event): boolean {
    return (e.currentTarget as HTMLInputElement).checked;
  }

  const setMode = (m: Mode) => patch({ mode: m });
  const setAlignTop = (a: Align) => patch({ align_top: a });
  const setAlignBottom = (a: Align) => patch({ align_bottom: a });
  const setAnimation = (a: Animation) => patch({ animation: a });
  const setScrollSpeed = (e: Event) => patch({ scroll_speed_ms: num(e) });

  // software scroll (mode "scroll") — per-row content source + scroll + dir.
  // SCROLL_SOURCES is the per-row "Source" selector; EXTENSION POINT: add
  // { value: 'news', label: 'News' } here when the news source lands.
  const SCROLL_SOURCES: { value: ScrollSource; label: string }[] = [
    { value: 'message', label: 'Message' },
    { value: 'clock', label: 'Clock' },
  ];
  // marquee (hardware ticker). Bottom is STATIC TEXT ONLY (a live clock there
  // stops the hardware scroll), so there's no source selector.
  let marqueeDraft = '';
  let marqueeSeen = '';
  $: if (state && state.marquee_text !== marqueeSeen) {
    marqueeSeen = state.marquee_text;
    marqueeDraft = state.marquee_text;
  }
  let marqueeTimer: ReturnType<typeof setTimeout> | null = null;
  function onMarqueeInput(): void {
    if (marqueeTimer) clearTimeout(marqueeTimer);
    marqueeTimer = setTimeout(() => patch({ marquee_text: marqueeDraft }), 250);
  }
  const setMarqueeBottomText = (e: Event) =>
    patch({ marquee_bottom_text: (e.target as HTMLInputElement).value });

  // spectrum analyzer. SOURCE = mic | system (PipeWire/Pulse monitor of
  // playback); DEVICE picks a specific input (from devices.json); gain/decay
  // tune sensitivity + smoothing. The live bar data arrives over a socket — these
  // are just settings the audioviz process reads from state.json.
  const SOURCES: { value: AudioSource; label: string }[] = [
    { value: 'system', label: 'System' },
    { value: 'mic', label: 'Mic' },
  ];
  let devicesLoaded = false;
  $: if (state?.mode === 'spectrum' && !devicesLoaded) {
    devicesLoaded = true;
    void refreshDevices();
  }
  // Show only the devices relevant to the chosen source: monitors for "system"
  // (loopback of playback), real inputs for "mic". Keeps the list scannable.
  $: devicesForSource = $audioDevices.filter((d) =>
    state?.audio_source === 'system' ? d.is_monitor : !d.is_monitor,
  );
  const setAudioSource = (s: AudioSource) => patch({ audio_source: s });
  function setAudioDevice(e: Event): void {
    const v = (e.target as HTMLSelectElement).value;
    patch({ audio_device: v === '' ? null : v });
  }
  const setAudioGain = (e: Event) => patch({ audio_gain: num(e) });
  const setAudioDecay = (e: Event) => patch({ audio_decay: num(e) });
  const STYLES: { value: SpectrumStyle; label: string }[] = [
    { value: 'bars', label: 'BARS' },
    { value: 'line', label: 'LINE' },
  ];
  const setSpectrumStyle = (s: SpectrumStyle) => patch({ spectrum_style: s });
  const LAYOUTS: { value: SpectrumLayout; label: string }[] = [
    { value: 'full', label: 'FULL' },
    { value: 'stereo_v', label: 'STEREO-V' },
    { value: 'stereo_h', label: 'STEREO-H' },
  ];
  const setSpectrumLayout = (l: SpectrumLayout) => patch({ spectrum_layout: l });

  // weather — location in decimal degrees (south/west negative), edited as
  // drafts and written ONLY on Save (so a half-typed value never triggers a
  // fetch). The drafts re-seed when the saved location changes elsewhere.
  let latDraft = '';
  let lonDraft = '';
  let seenLoc = '';
  $: if (state) {
    const loc = `${state.weather_lat ?? ''},${state.weather_lon ?? ''}`;
    if (loc !== seenLoc) {
      seenLoc = loc;
      latDraft = state.weather_lat == null ? '' : String(state.weather_lat);
      lonDraft = state.weather_lon == null ? '' : String(state.weather_lon);
    }
  }
  $: latValue = parseCoord(latDraft, 90);
  $: lonValue = parseCoord(lonDraft, 180);
  $: locValid = latValue !== undefined && lonValue !== undefined;
  $: locDirty =
    locValid &&
    (latValue !== (state?.weather_lat ?? null) || lonValue !== (state?.weather_lon ?? null));
  function saveLocation(): void {
    if (!locValid || latValue === undefined || lonValue === undefined) return;
    patch({ weather_lat: latValue, weather_lon: lonValue });
  }
  const COLONS: { value: DynamicColon; label: string }[] = [
    { value: 'on', label: 'ON' },
    { value: 'tick', label: 'TICK' },
    { value: 'wiggle', label: 'WIGGLE' },
    { value: 'twinkle', label: 'TWINKLE' },
    { value: 'pacman', label: 'PACMAN' },
  ];
  const setColon = (c: DynamicColon) => patch({ dynamic_colon: c });
  const setColonHalf = (e: Event) => patch({ dynamic_colon_half: checked(e) });
  // pacman: Solo shows one sprite; the chosen sprite is remembered while Solo
  // is off, because the widest date/time forces solo with it automatically.
  const SPRITES: { value: DynamicPacmanSprite; label: string }[] = [
    { value: 'ghost', label: 'GHOST' },
    { value: 'heart', label: 'HEART' },
    { value: 'pacman', label: 'PACMAN' },
  ];
  const setSolo = (e: Event) => patch({ dynamic_pacman_solo: checked(e) });
  const setSprite = (p: DynamicPacmanSprite) => patch({ dynamic_pacman_sprite: p });
  $: weatherLine = weatherSummary(status?.weather);

  // One line per colon choice: only the selected one is explained.
  const COLON_HINTS: Record<DynamicColon, string> = {
    on: 'A steady colon.',
    tick: 'The colon blinks every second.',
    wiggle: 'The colon twists one way, then the other.',
    twinkle: 'The colon grows into a burst and back.',
    pacman: 'Pacman eats the chosen sprite; Solo shows it alone (automatic when the date fills the line).',
  };

  // Message rows: one template for top and bottom, via these helpers.
  type Row = 'top' | 'bottom';
  const ROWS: { row: Row; label: string }[] = [
    { row: 'top', label: 'Top' },
    { row: 'bottom', label: 'Bottom' },
  ];
  const rowSource = (r: Row): ScrollSource =>
    (r === 'top' ? state?.scroll_top_source : state?.scroll_bottom_source) ?? 'message';
  const rowScrolls = (r: Row): boolean =>
    !!(r === 'top' ? state?.scroll_top : state?.scroll_bottom);
  const rowDir = (r: Row): ScrollDir =>
    (r === 'top' ? state?.scroll_dir_top : state?.scroll_dir_bottom) ?? 'left';
  const setRowSource = (r: Row, v: ScrollSource) =>
    patch(r === 'top' ? { scroll_top_source: v } : { scroll_bottom_source: v });
  const setRowScroll = (r: Row, e: Event) =>
    patch(r === 'top' ? { scroll_top: checked(e) } : { scroll_bottom: checked(e) });
  const setRowDir = (r: Row, d: ScrollDir) =>
    patch(r === 'top' ? { scroll_dir_top: d } : { scroll_dir_bottom: d });
  // Re-evaluate the helpers whenever the state object changes.
  $: rowsView = state &&
    ROWS.map((x) => ({ ...x, source: rowSource(x.row), scrolls: rowScrolls(x.row), dir: rowDir(x.row) }));
  $: anyScroll = !!(state?.scroll_top || state?.scroll_bottom);

  const DIRS: ScrollDir[] = ['left', 'right'];
  // Merge one animation_params field, keeping the siblings (full object so the
  // Partial<AppState> type is satisfied; the backend deep-merges anyway).
  function patchParams(field: 'on_ms' | 'off_ms' | 'step_ms', e: Event): void {
    const cur = state?.animation_params ?? { on_ms: 500, off_ms: 500, step_ms: 200 };
    patch({ animation_params: { ...cur, [field]: num(e) } });
  }
  const setOnMs = (e: Event) => patchParams('on_ms', e);
  const setOffMs = (e: Event) => patchParams('off_ms', e);
  const setStepMs = (e: Event) => patchParams('step_ms', e);
</script>

<section class="panel">
  <div class="panel__title">Control</div>

  {#if !state}
    <p class="loading">connecting to daemon…</p>
  {:else}
    <div class="field">
      <span class="field__label">Mode</span>
      <div class="seg">
        {#each MODES as m}
          <button type="button" aria-pressed={state.mode === m} on:click={() => setMode(m)}>{m}</button>
        {/each}
      </div>
    </div>

    <!-- MESSAGE: text + per-row source / scroll / direction (was also "scroll") -->
    {#if state.mode === 'message'}
      <div class="field">
        <span class="field__label">
          Message
          <!-- Length is only flagged while nothing scrolls. -->
          {#if !anyScroll}
            {#if budget.hasNewline}
              <span class="budget">
                <span class:over={budget.topOver}>{budget.top}/20</span>
                <span class="sep">·</span>
                <span class:over={budget.bottomOver}>{budget.bottom}/20</span>
              </span>
            {:else}
              <span class:over={budget.topOver}>{budget.top}/20</span>
            {/if}
          {/if}
        </span>
        <textarea
          rows="2"
          bind:value={messageDraft}
          on:input={onMessageInput}
          placeholder="message"
          spellcheck="false"
        ></textarea>
        <span class="field__hint">
          <kbd>Enter</kbd> = new line · <code>{'{g0}'}</code>–<code>{'{g8}'}</code> = custom glyphs
        </span>
      </div>

      <div class="field">
        <span class="field__label">Rows</span>
        {#each rowsView ?? [] as r (r.row)}
          <div class="ctl-row">
            <span class="ctl-row__name">{r.label}</span>
            <div class="seg seg--sm">
              {#each SCROLL_SOURCES as src}
                <button
                  type="button"
                  aria-pressed={r.source === src.value}
                  on:click={() => setRowSource(r.row, src.value)}>{src.label}</button
                >
              {/each}
            </div>
            {#if r.source === 'message'}
              <label class="switch">
                <input type="checkbox" checked={r.scrolls} on:change={(e) => setRowScroll(r.row, e)} />
                <span class="switch__track"></span>
                <span class="switch__label">Scroll</span>
              </label>
              {#if r.scrolls}
                <div class="seg seg--sm">
                  {#each DIRS as d}
                    <button
                      type="button"
                      aria-pressed={r.dir === d}
                      on:click={() => setRowDir(r.row, d)}>{d}</button
                    >
                  {/each}
                </div>
              {/if}
            {/if}
          </div>
        {/each}
        {#if anyScroll}
          <label class="ctl-row">
            <span class="ctl-row__name">Speed</span>
            <input type="number" min="60" step="20" value={state.scroll_speed_ms} on:change={setScrollSpeed} />
            <span class="field__hint">ms per step</span>
          </label>
        {/if}
      </div>
    {/if}

    <!-- MARQUEE: hidden from MODES (v1.4.0) but still works if selected. -->
    {#if state.mode === 'marquee'}
      <div class="field">
        <span class="field__label">
          Marquee text
          <span class:over={marqueeDraft.length > 45}>{marqueeDraft.length}/45</span>
        </span>
        <input type="text" bind:value={marqueeDraft} on:input={onMarqueeInput} spellcheck="false" />
        <span class="field__hint">Hardware ticker: top row, fixed speed.</span>
      </div>
      <div class="field">
        <span class="field__label">Bottom row</span>
        <input
          type="text"
          value={state.marquee_bottom_text}
          on:change={setMarqueeBottomText}
          spellcheck="false"
        />
      </div>
    {/if}

    <!-- SPECTRUM: settings only; the bars stream from the audioviz process. -->
    {#if state.mode === 'spectrum'}
      <div class="field">
        <span class="field__label">Source</span>
        <div class="seg">
          {#each SOURCES as src}
            <button
              type="button"
              aria-pressed={state.audio_source === src.value}
              on:click={() => setAudioSource(src.value)}>{src.label}</button
            >
          {/each}
        </div>
        <span class="field__hint">System = what's playing · Mic = the default input</span>
      </div>

      <div class="field">
        <span class="field__label">Layout</span>
        <div class="seg">
          {#each LAYOUTS as l}
            <button
              type="button"
              aria-pressed={state.spectrum_layout === l.value}
              on:click={() => setSpectrumLayout(l.value)}>{l.label}</button
            >
          {/each}
        </div>
        <span class="field__hint">Full = mono · Stereo-V = a spectrum per channel · Stereo-H = level meters</span>
      </div>

      <div class="field">
        <span class="field__label">Style</span>
        <div class="seg">
          {#each STYLES as st}
            <button
              type="button"
              aria-pressed={state.spectrum_style === st.value}
              on:click={() => setSpectrumStyle(st.value)}>{st.label}</button
            >
          {/each}
        </div>
      </div>

      <div class="field">
        <span class="field__label">Device</span>
        <select value={state.audio_device ?? ''} on:change={setAudioDevice}>
          <option value="">
            {state.audio_source === 'system' ? 'Auto (default output)' : 'Auto (default input)'}
          </option>
          {#each devicesForSource as d}
            <option value={d.id}>{d.label}</option>
          {/each}
        </select>
        {#if devicesForSource.length === 0}
          <span class="field__hint">
            None found — run <code>python -m checkout.audioviz --list</code>
          </span>
        {/if}
      </div>

      <div class="field">
        <span class="field__label">
          Sensitivity <span class="readout">{state.audio_gain.toFixed(1)}×</span>
        </span>
        <input
          class="phosphor-slider"
          type="range" min="0.3" max="3" step="0.1"
          aria-label="sensitivity"
          value={state.audio_gain}
          on:input={setAudioGain}
        />
      </div>

      <div class="field">
        <span class="field__label">
          Smoothing <span class="readout">{state.audio_decay.toFixed(2)}</span>
        </span>
        <input
          class="phosphor-slider"
          type="range" min="0" max="0.98" step="0.01"
          aria-label="smoothing"
          value={state.audio_decay}
          on:input={setAudioDecay}
        />
        <span class="field__hint">Uses all 9 glyph slots; your glyphs come back when you leave.</span>
      </div>
    {/if}

    <!-- DYNAMIC: date/time on top, the next 24 h of weather below. -->
    {#if state.mode === 'dynamic'}
      <div class="field">
        <span class="field__label">Weather location</span>
        <form class="coords" on:submit|preventDefault={saveLocation}>
          <input
            type="text" inputmode="decimal" spellcheck="false"
            aria-label="latitude" placeholder="latitude"
            class:invalid={latValue === undefined}
            bind:value={latDraft}
          />
          <input
            type="text" inputmode="decimal" spellcheck="false"
            aria-label="longitude" placeholder="longitude"
            class:invalid={lonValue === undefined}
            bind:value={lonDraft}
          />
          <button type="submit" class="btn" disabled={!locDirty}>Save</button>
        </form>
        <span class="field__hint">
          {#if !locValid}
            <span class="over">Latitude is −90 to 90, longitude −180 to 180.</span>
          {:else if state.weather_lat == null}
            Decimal degrees; south and west are negative.
          {:else}
            {weatherLine}
          {/if}
        </span>
      </div>

      <div class="field">
        <span class="field__label">Time features</span>
        <div class="seg">
          {#each COLONS as c}
            <button
              type="button"
              aria-pressed={state.dynamic_colon === c.value}
              on:click={() => setColon(c.value)}>{c.label}</button
            >
          {/each}
        </div>
        <div class="ctl-row">
          <label class="switch" class:disabled={state.dynamic_colon === 'on'}>
            <input
              type="checkbox"
              checked={state.dynamic_colon_half}
              disabled={state.dynamic_colon === 'on'}
              on:change={setColonHalf}
            />
            <span class="switch__track"></span>
            <span class="switch__label">Half speed</span>
          </label>
          {#if state.dynamic_colon === 'pacman'}
            <label class="switch">
              <input type="checkbox" checked={state.dynamic_pacman_solo} on:change={setSolo} />
              <span class="switch__track"></span>
              <span class="switch__label">Solo</span>
            </label>
            <div class="seg seg--sm">
              {#each SPRITES as p}
                <button
                  type="button"
                  aria-pressed={state.dynamic_pacman_sprite === p.value}
                  on:click={() => setSprite(p.value)}>{p.label}</button
                >
              {/each}
            </div>
          {/if}
        </div>
        <span class="field__hint">{COLON_HINTS[state.dynamic_colon]}</span>
      </div>
    {/if}

    <!-- Justify: N/A in spectrum (bars) and dynamic (always centred). In the
         hidden marquee mode only the static bottom line justifies. -->
    {#if state.mode !== 'spectrum' && state.mode !== 'dynamic'}
      <div class="field">
        <span class="field__label">Justify</span>
        {#if state.mode !== 'marquee'}
          <div class="ctl-row">
            <span class="ctl-row__name">Line 1</span>
            <div class="seg seg--sm">
              {#each ALIGNS as a}
                <button type="button" aria-pressed={state.align_top === a} on:click={() => setAlignTop(a)}>{a}</button>
              {/each}
            </div>
          </div>
        {/if}
        <div class="ctl-row">
          <span class="ctl-row__name">Line 2</span>
          <div class="seg seg--sm">
            {#each ALIGNS as a}
              <button type="button" aria-pressed={state.align_bottom === a} on:click={() => setAlignBottom(a)}>{a}</button>
            {/each}
          </div>
        </div>
      </div>
    {/if}

    <!-- Animation: N/A where the mode owns the rows (marquee, spectrum) or
         animates its own colon (dynamic). -->
    {#if state.mode !== 'marquee' && state.mode !== 'spectrum' && state.mode !== 'dynamic'}
      <div class="field">
        <span class="field__label">Animation</span>
        <div class="seg">
          {#each ANIMATIONS as a}
            <button type="button" aria-pressed={state.animation === a} on:click={() => setAnimation(a)}>{a}</button>
          {/each}
        </div>
        {#if state.animation === 'flash' || state.animation === 'blink'}
          <div class="ctl-row">
            <span class="ctl-row__name">On</span>
            <input type="number" min="50" step="50" value={state.animation_params.on_ms} on:change={setOnMs} />
            <span class="ctl-row__name">Off</span>
            <input type="number" min="50" step="50" value={state.animation_params.off_ms} on:change={setOffMs} />
            <span class="field__hint">ms</span>
          </div>
        {:else if state.animation === 'pulse'}
          <div class="ctl-row">
            <span class="ctl-row__name">Step</span>
            <input type="number" min="50" step="50" value={state.animation_params.step_ms} on:change={setStepMs} />
            <span class="field__hint">ms per brightness step</span>
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</section>

<style>
  .loading {
    color: var(--text-mute);
    font-size: 13px;
  }

  /* lat | lon | Save — three equal columns */
  .coords {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .coords input,
  .coords .btn {
    width: 100%;
    min-width: 0;
    margin: 0;
  }

  .coords input.invalid {
    border-color: var(--red-dead);
  }

  .over {
    color: var(--amber-warn);
  }

  .field__label .over {
    font-weight: 600;
  }

  .budget {
    display: inline-flex;
    gap: 5px;
  }

  .switch.disabled {
    opacity: 0.4;
  }
</style>
