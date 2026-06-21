<script lang="ts">
  import { lineBudget } from '../message';
  import type {
    Align,
    AppState,
    Animation,
    Brightness,
    MarqueeBottom,
    Mode,
    ScrollDir,
  } from '../types';

  export let state: AppState | null = null;
  export let patch: (p: Partial<AppState>) => void;

  const MODES: Mode[] = ['clock', 'message', 'scroll', 'marquee'];
  // Brightness has FOUR discrete levels (index 0..3); a stepped slider, NOT a %.
  const BRIGHTNESS_LABELS = ['MIN', 'MED', 'MED+', 'MAX'];
  const ANIMATIONS: Animation[] = ['none', 'flash', 'blink', 'pulse'];
  const ALIGNS: Align[] = ['left', 'center', 'right'];
  const CODE_PAGES: { value: number; label: string }[] = [
    { value: 0, label: 'Default' },
    { value: 1, label: 'Japanese' },
    { value: 2, label: 'CP850' },
    { value: 3, label: 'CP852' },
    { value: 4, label: 'CP855' },
    { value: 5, label: 'CP857' },
  ];

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
  const setBrightness = (e: Event) =>
    patch({ brightness: clampLevel(num(e)) });
  function clampLevel(n: number): Brightness {
    return Math.max(0, Math.min(3, Math.round(n))) as Brightness;
  }
  const setAnimation = (a: Animation) => patch({ animation: a });
  const setBlank = (e: Event) => patch({ blank: checked(e) });
  const setScroll = (e: Event) => patch({ scroll: checked(e) });
  const setCodePage = (e: Event) => patch({ code_page: num(e) });
  const setScrollSpeed = (e: Event) => patch({ scroll_speed_ms: num(e) });

  // software scroll (mode "scroll")
  const setScrollTop = (e: Event) => patch({ scroll_top: checked(e) });
  const setScrollBottom = (e: Event) => patch({ scroll_bottom: checked(e) });
  const setDirTop = (d: ScrollDir) => patch({ scroll_dir_top: d });
  const setDirBottom = (d: ScrollDir) => patch({ scroll_dir_bottom: d });
  // marquee (hardware ticker)
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
  const MARQUEE_BOTTOMS: MarqueeBottom[] = ['static', 'clock'];
  const setMarqueeBottom = (b: MarqueeBottom) => patch({ marquee_bottom: b });
  const setMarqueeBottomText = (e: Event) =>
    patch({ marquee_bottom_text: (e.target as HTMLInputElement).value });

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
          {#if budget.hasNewline}
            <span class="budget">
              <span class:over={budget.topOver}>top {budget.top}/20</span>
              <span class="sep">·</span>
              <span class:over={budget.bottomOver}>bottom {budget.bottom}/20</span>
            </span>
          {:else}
            <span class:over={budget.topOver}>{budget.top}/20</span>
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
        <span class="field__label">Bottom row</span>
        <div class="seg">
          {#each MARQUEE_BOTTOMS as b}
            <button
              type="button"
              aria-pressed={state.marquee_bottom === b}
              on:click={() => setMarqueeBottom(b)}>{b}</button
            >
          {/each}
        </div>
        {#if state.marquee_bottom === 'static'}
          <input
            type="text"
            value={state.marquee_bottom_text}
            on:change={setMarqueeBottomText}
            placeholder="static bottom text (≤20)"
            spellcheck="false"
          />
        {/if}
      </div>
    {/if}

    <!-- Per-line alignment -->
    <div class="field">
      <span class="field__label">Justify</span>
      <div class="align-rows">
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

    <!-- Brightness + scroll -->
    <div class="field">
      <span class="field__label">
        Brightness
        <span class="bright-readout">{BRIGHTNESS_LABELS[clampLevel(state.brightness)]}</span>
      </span>
      <div class="bright">
        <input
          class="bright__slider"
          type="range"
          min="0"
          max="3"
          step="1"
          aria-label="brightness level"
          value={clampLevel(state.brightness)}
          on:input={setBrightness}
        />
        <div class="bright__stops" aria-hidden="true">
          {#each BRIGHTNESS_LABELS as label, i}
            <button
              type="button"
              class="bright__stop"
              class:active={clampLevel(state.brightness) === i}
              on:click={() => patch({ brightness: clampLevel(i) })}>{label}</button
            >
          {/each}
        </div>
      </div>
    </div>

    <div class="row switches">
      <label class="switch">
        <input type="checkbox" checked={state.blank} on:change={setBlank} />
        <span class="switch__track"></span>
        <span class="switch__label">Blank</span>
      </label>

      <label class="switch" title="Hardware vertical scroll — for marquee effects">
        <input type="checkbox" checked={state.scroll} on:change={setScroll} />
        <span class="switch__track"></span>
        <span class="switch__label">HW scroll</span>
      </label>
    </div>

    <!-- Code page -->
    <div class="field">
      <span class="field__label">Code page</span>
      <select value={state.code_page} on:change={setCodePage}>
        {#each CODE_PAGES as cp}
          <option value={cp.value}>{cp.value} · {cp.label}</option>
        {/each}
      </select>
    </div>

    <!-- Animation -->
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

    <!-- SCROLL: per-row scroll + direction + speed -->
    {#if state.mode === 'scroll'}
      <div class="field">
        <span class="field__label">Scroll rows</span>
        <div class="align-rows">
          <div class="align-row">
            <label class="switch">
              <input type="checkbox" checked={state.scroll_top} on:change={setScrollTop} />
              <span class="switch__track"></span>
              <span class="switch__label">Line 1</span>
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
          <div class="align-row">
            <label class="switch">
              <input type="checkbox" checked={state.scroll_bottom} on:change={setScrollBottom} />
              <span class="switch__track"></span>
              <span class="switch__label">Line 2</span>
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

  .switches {
    margin-bottom: 14px;
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

  /* brightness: a 4-stop stepped slider (NOT a continuous %) */
  .bright {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .bright-readout {
    color: var(--phosphor);
    letter-spacing: 0.1em;
  }

  .bright__slider {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    padding: 0;
    border-radius: 3px;
    background: linear-gradient(
      90deg,
      var(--phosphor-deep),
      var(--phosphor-dim),
      var(--phosphor)
    );
    box-shadow: var(--shadow-inset);
    cursor: pointer;
  }

  .bright__slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 14px;
    height: 18px;
    border-radius: 3px;
    background: var(--phosphor-ink);
    border: 1px solid var(--phosphor);
    box-shadow: 0 0 8px var(--phosphor);
  }

  .bright__slider::-moz-range-thumb {
    width: 14px;
    height: 18px;
    border-radius: 3px;
    background: var(--phosphor-ink);
    border: 1px solid var(--phosphor);
    box-shadow: 0 0 8px var(--phosphor);
  }

  .bright__stops {
    display: flex;
    justify-content: space-between;
  }

  .bright__stop {
    appearance: none;
    background: none;
    border: 0;
    padding: 0;
    font-family: var(--mono);
    font-size: 9px;
    letter-spacing: 0.08em;
    color: var(--text-faint);
    cursor: pointer;
  }

  .bright__stop.active {
    color: var(--phosphor);
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
