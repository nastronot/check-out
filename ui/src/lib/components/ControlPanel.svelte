<script lang="ts">
  import { lineBudget } from '../message';
  import { audioDevices, refreshDevices } from '../stores';
  import type {
    Align,
    AppState,
    Animation,
    AudioSource,
    Mode,
    ScrollDir,
    ScrollSource,
  } from '../types';

  export let state: AppState | null = null;
  export let patch: (p: Partial<AppState>) => void;

  const MODES: Mode[] = ['clock', 'message', 'scroll', 'marquee', 'spectrum'];
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
  const setSrcTop = (s: ScrollSource) => patch({ scroll_top_source: s });
  const setSrcBottom = (s: ScrollSource) => patch({ scroll_bottom_source: s });
  const setScrollTop = (e: Event) => patch({ scroll_top: checked(e) });
  const setScrollBottom = (e: Event) => patch({ scroll_bottom: checked(e) });
  const setDirTop = (d: ScrollDir) => patch({ scroll_dir_top: d });
  const setDirBottom = (d: ScrollDir) => patch({ scroll_dir_bottom: d });
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
    <!-- Mode -->
    <div class="field">
      <span class="field__label">Mode</span>
      <div class="seg">
        {#each MODES as m}
          <button
            type="button"
            aria-pressed={state.mode === m}
            on:click={() => setMode(m)}>{m}</button
          >
        {/each}
      </div>
    </div>

    <!-- Message (drives message + scroll modes) -->
    {#if state.mode === 'message' || state.mode === 'scroll'}
      <div class="field">
        <span class="field__label">
          Message
          <!-- Budget warning is MESSAGE-only: in SCROLL mode long text is the
               point (it scrolls), so length is never flagged there. -->
          {#if state.mode === 'message'}
            {#if budget.hasNewline}
              <span class="budget">
                <span class:over={budget.topOver}>top {budget.top}/20</span>
                <span class="sep">·</span>
                <span class:over={budget.bottomOver}>bottom {budget.bottom}/20</span>
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
          placeholder="message (Enter = line break)"
          spellcheck="false"
        ></textarea>
        <span class="field__hint">
          Press <kbd>Enter</kbd> for a line break (splits top/bottom). Use
          <code>{'{g0}'}</code>…<code>{'{g8}'}</code> for custom glyphs (light up
          once defined).{#if state.mode === 'scroll'} In SCROLL mode each line can
          scroll independently (below); long lines scroll, short ones sit aligned.{/if}
        </span>
      </div>
    {/if}

    <!-- MARQUEE (hardware ticker: top autonomous, FIXED speed) -->
    {#if state.mode === 'marquee'}
      <div class="field">
        <span class="field__label">
          Marquee text
          <span class:over={marqueeDraft.length > 45}>{marqueeDraft.length}/45</span>
        </span>
        <input
          type="text"
          bind:value={marqueeDraft}
          on:input={onMarqueeInput}
          placeholder="scrolls on the top row (hardware ticker)"
          spellcheck="false"
        />
        <span class="field__hint">
          Top row scrolls autonomously at the hardware's FIXED speed (no speed
          control). 45-char buffer.
        </span>
      </div>
      <div class="field">
        <span class="field__label">Bottom row (static)</span>
        <input
          type="text"
          value={state.marquee_bottom_text}
          on:change={setMarqueeBottomText}
          placeholder="static bottom text (≤20)"
          spellcheck="false"
        />
      </div>
      <p class="tip">
        Hardware ticker: top row only, fixed speed, 45-char buffer. The bottom row
        is static — changing it briefly interrupts the top scroll. For a live
        clock/news ticker, use <strong>SCROLL</strong>.
      </p>
    {/if}

    <!-- SPECTRUM (audio analyzer: a separate audioviz process captures + FFTs
         and streams 20 bar heights to the daemon over a socket). -->
    {#if state.mode === 'spectrum'}
      <div class="field">
        <span class="field__label">Source</span>
        <div class="seg">
          {#each SOURCES as s}
            <button
              type="button"
              aria-pressed={state.audio_source === s.value}
              on:click={() => setAudioSource(s.value)}>{s.label}</button
            >
          {/each}
        </div>
        <span class="field__hint">
          <strong>System</strong> captures playback via a PipeWire/Pulse monitor;
          <strong>Mic</strong> captures the default input. Bars are
          <strong>volume-independent</strong> (auto-gain) and fall to flat on
          silence.
        </span>
      </div>

      <div class="field">
        <span class="field__label">Device</span>
        <select value={state.audio_device ?? ''} on:change={setAudioDevice}>
          <option value="">
            {state.audio_source === 'system'
              ? 'Auto (default sink monitor)'
              : 'Auto (default input)'}
          </option>
          {#each devicesForSource as d}
            <option value={d.id}>{d.label}</option>
          {/each}
        </select>
        {#if devicesForSource.length === 0}
          <span class="field__hint">
            {#if state.audio_source === 'system'}
              No monitor sources found — needs PipeWire/Pulse. Run
              <code>python -m checkout.audioviz --list</code>.
            {:else}
              No input devices listed — run
              <code>python -m checkout.audioviz --list</code>.
            {/if}
          </span>
        {/if}
      </div>

      <div class="field">
        <span class="field__label">
          Sensitivity <span class="bright-readout">{state.audio_gain.toFixed(1)}×</span>
        </span>
        <input
          type="range" min="0.3" max="3" step="0.1"
          aria-label="sensitivity"
          value={state.audio_gain}
          on:input={setAudioGain}
        />
        <span class="field__hint">
          Auto-gain keeps the bars full regardless of system volume; sensitivity
          biases it (center is fine for most content).
        </span>
      </div>

      <div class="field">
        <span class="field__label">
          Smoothing <span class="bright-readout">{state.audio_decay.toFixed(2)}</span>
        </span>
        <input
          type="range" min="0.5" max="0.98" step="0.01"
          aria-label="audio decay"
          value={state.audio_decay}
          on:input={setAudioDecay}
        />
        <span class="field__hint">Higher = bars fall more slowly (less twitch).</span>
      </div>

      <p class="tip">
        Spectrum uses the 9 glyph slots for the bars — your custom glyphs pause
        during spectrum and restore on exit.
      </p>
    {/if}

    <!-- Per-line alignment. In MARQUEE the top row is the hardware ticker (it
         controls its own layout), so Line 1 justify is hidden; Line 2 (the
         static bottom) still justifies. N/A in SPECTRUM (both rows are bars). -->
    {#if state.mode !== 'spectrum'}
    <div class="field">
      <span class="field__label">Justify</span>
      <div class="align-rows">
        {#if state.mode !== 'marquee'}
          <div class="align-row">
            <span class="align-row__label">Line 1</span>
            <div class="seg seg--sm">
              {#each ALIGNS as a}
                <button
                  type="button"
                  aria-pressed={state.align_top === a}
                  on:click={() => setAlignTop(a)}>{a}</button
                >
              {/each}
            </div>
          </div>
        {:else}
          <p class="field__hint">
            Line 1 is the hardware ticker (it sets its own layout). Line 2 justify
            applies to the static bottom.
          </p>
        {/if}
        <div class="align-row">
          <span class="align-row__label">Line 2</span>
          <div class="seg seg--sm">
            {#each ALIGNS as a}
              <button
                type="button"
                aria-pressed={state.align_bottom === a}
                on:click={() => setAlignBottom(a)}>{a}</button
              >
            {/each}
          </div>
        </div>
      </div>
    </div>
    {/if}

    <!-- Brightness, Blank, HW scroll, and Code page now live in the Display
         panel (mode-agnostic device settings). Control is per-mode only. -->

    <!-- Animation (N/A in marquee: the ticker owns the top row; N/A in
         spectrum: the bars own both rows and the daemon forces "none"). -->
    {#if state.mode !== 'marquee' && state.mode !== 'spectrum'}
    <div class="field">
      <span class="field__label">Animation</span>
      <div class="seg">
        {#each ANIMATIONS as a}
          <button
            type="button"
            aria-pressed={state.animation === a}
            on:click={() => setAnimation(a)}>{a}</button
          >
        {/each}
      </div>
      {#if state.animation === 'flash' || state.animation === 'blink'}
        <div class="row timing">
          <label class="field__hint">on
            <input
              type="number"
              min="50"
              step="50"
              value={state.animation_params.on_ms}
              on:change={setOnMs}
            /> ms</label>
          <label class="field__hint">off
            <input
              type="number"
              min="50"
              step="50"
              value={state.animation_params.off_ms}
              on:change={setOffMs}
            /> ms</label>
        </div>
      {:else if state.animation === 'pulse'}
        <div class="row timing">
          <label class="field__hint">step
            <input
              type="number"
              min="50"
              step="50"
              value={state.animation_params.step_ms}
              on:change={setStepMs}
            /> ms</label>
          <span class="field__hint">brightness breathes 0→3→0 (6 steps)</span>
        </div>
      {/if}
    </div>
    {/if}

    <!-- SCROLL: per-row content source + scroll + direction + speed. The
         flexible, news-ready mode: each row picks a source (Message|Clock, room
         for more) and, for a Message row, whether/how it scrolls. -->
    {#if state.mode === 'scroll'}
      <div class="field">
        <span class="field__label">Scroll rows</span>
        <div class="scroll-rows">
          <!-- TOP row -->
          <div class="scroll-row">
            <span class="scroll-row__name">Top</span>
            <div class="scroll-row__ctrls">
              <div class="scroll-ctrl">
                <span class="scroll-ctrl__label">Source</span>
                <div class="seg seg--sm">
                  {#each SCROLL_SOURCES as s}
                    <button
                      type="button"
                      aria-pressed={state.scroll_top_source === s.value}
                      on:click={() => setSrcTop(s.value)}>{s.label}</button
                    >
                  {/each}
                </div>
              </div>
              {#if state.scroll_top_source === 'message'}
                <div class="scroll-ctrl scroll-ctrl--inline">
                  <label class="switch">
                    <input type="checkbox" checked={state.scroll_top} on:change={setScrollTop} />
                    <span class="switch__track"></span>
                    <span class="switch__label">Scroll</span>
                  </label>
                  <div class="seg seg--sm" class:disabled={!state.scroll_top}>
                    {#each DIRS as d}
                      <button
                        type="button"
                        disabled={!state.scroll_top}
                        aria-pressed={state.scroll_dir_top === d}
                        on:click={() => setDirTop(d)}>{d}</button
                      >
                    {/each}
                  </div>
                </div>
              {:else}
                <span class="field__hint">Live time line (updates each second).</span>
              {/if}
            </div>
          </div>
          <!-- BOTTOM row -->
          <div class="scroll-row">
            <span class="scroll-row__name">Bottom</span>
            <div class="scroll-row__ctrls">
              <div class="scroll-ctrl">
                <span class="scroll-ctrl__label">Source</span>
                <div class="seg seg--sm">
                  {#each SCROLL_SOURCES as s}
                    <button
                      type="button"
                      aria-pressed={state.scroll_bottom_source === s.value}
                      on:click={() => setSrcBottom(s.value)}>{s.label}</button
                    >
                  {/each}
                </div>
              </div>
              {#if state.scroll_bottom_source === 'message'}
                <div class="scroll-ctrl scroll-ctrl--inline">
                  <label class="switch">
                    <input type="checkbox" checked={state.scroll_bottom} on:change={setScrollBottom} />
                    <span class="switch__track"></span>
                    <span class="switch__label">Scroll</span>
                  </label>
                  <div class="seg seg--sm" class:disabled={!state.scroll_bottom}>
                    {#each DIRS as d}
                      <button
                        type="button"
                        disabled={!state.scroll_bottom}
                        aria-pressed={state.scroll_dir_bottom === d}
                        on:click={() => setDirBottom(d)}>{d}</button
                      >
                    {/each}
                  </div>
                </div>
              {:else}
                <span class="field__hint">Live time line (updates each second).</span>
              {/if}
            </div>
          </div>
        </div>
      </div>
      <div class="field">
        <span class="field__label">Scroll speed</span>
        <label class="field__hint">
          <input
            type="number"
            min="60"
            step="20"
            value={state.scroll_speed_ms}
            on:change={setScrollSpeed}
          /> ms / step (floor ~60 — 9600 baud can't go faster)
        </label>
      </div>
    {/if}
  {/if}
</section>

<style>
  .loading {
    color: var(--text-mute);
    font-size: 13px;
  }

  .timing {
    margin-top: 10px;
  }

  .timing input,
  .field__hint input {
    margin: 0 4px;
  }

  code {
    color: var(--phosphor);
    background: #04090a;
    padding: 1px 4px;
    border-radius: 3px;
    border: 1px solid var(--rule);
    font-size: 11px;
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

  /* marquee constraints tip */
  .tip {
    margin: -4px 0 14px;
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-mute);
    border-left: 2px solid var(--phosphor-dim);
    padding: 6px 0 6px 10px;
  }

  .tip strong {
    color: var(--phosphor);
  }

  /* SCROLL: per-row source / scroll / direction, grouped + room to grow */
  .scroll-rows {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .scroll-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--rule);
  }

  .scroll-row:last-child {
    border-bottom: 0;
    padding-bottom: 0;
  }

  .scroll-row__name {
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--phosphor-dim);
  }

  .scroll-row__ctrls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 16px;
  }

  .scroll-ctrl {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .scroll-ctrl--inline {
    gap: 10px;
  }

  .scroll-ctrl__label {
    font-size: 11px;
    letter-spacing: 0.06em;
    color: var(--text-mute);
  }

  .align-rows {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .align-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .align-row__label {
    font-size: 11px;
    letter-spacing: 0.06em;
    color: var(--text-mute);
    min-width: 44px;
  }

  .seg--sm button {
    padding: 6px 12px;
    font-size: 11px;
  }

  .seg.disabled {
    opacity: 0.4;
  }

  .seg button:disabled {
    cursor: not-allowed;
  }

  .budget .sep {
    color: var(--text-faint);
  }

  textarea {
    /* keep both display lines visible; no horizontal wrap surprises */
    white-space: pre-wrap;
    word-break: break-word;
  }

  kbd {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--phosphor);
    background: #04090a;
    border: 1px solid var(--rule);
    border-radius: 3px;
    padding: 0 4px;
  }
</style>
