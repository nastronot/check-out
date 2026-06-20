<script lang="ts">
  import { lineBudget } from '../message';
  import type { Align, AppState, Animation, Brightness, Mode } from '../types';

  export let state: AppState | null = null;
  export let patch: (p: Partial<AppState>) => void;

  const MODES: Mode[] = ['clock', 'message', 'ticker'];
  const BRIGHTNESSES: Brightness[] = ['dim', 'bright'];
  const ANIMATIONS: Animation[] = ['none', 'flash', 'blink'];
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
  const setBrightness = (b: Brightness) => patch({ brightness: b });
  const setAnimation = (a: Animation) => patch({ animation: a });
  const setBlank = (e: Event) => patch({ blank: checked(e) });
  const setScroll = (e: Event) => patch({ scroll: checked(e) });
  const setCodePage = (e: Event) => patch({ code_page: num(e) });
  const setTickerSpeed = (e: Event) => patch({ scroll_speed_ms: num(e) });
  const setOnMs = (e: Event) =>
    patch({
      animation_params: {
        on_ms: num(e),
        off_ms: state?.animation_params.off_ms ?? 500,
      },
    });
  const setOffMs = (e: Event) =>
    patch({
      animation_params: {
        on_ms: state?.animation_params.on_ms ?? 500,
        off_ms: num(e),
      },
    });
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

    <!-- Message -->
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
        once defined).
      </span>
    </div>

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
      <span class="field__label">Brightness</span>
      <div class="seg">
        {#each BRIGHTNESSES as b}
          <button
            type="button"
            aria-pressed={state.brightness === b}
            on:click={() => setBrightness(b)}>{b}</button
          >
        {/each}
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
      {#if state.animation !== 'none'}
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
      {/if}
    </div>

    <!-- Ticker speed -->
    {#if state.mode === 'ticker'}
      <div class="field">
        <span class="field__label">Ticker speed</span>
        <label class="field__hint">
          <input
            type="number"
            min="50"
            step="50"
            value={state.scroll_speed_ms}
            on:change={setTickerSpeed}
          /> ms / step
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
