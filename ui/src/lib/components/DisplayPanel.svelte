<script lang="ts">
  import type { AppState, Brightness } from '../types';

  // Mode-agnostic DEVICE settings (apply regardless of mode): brightness, blank,
  // hardware vertical-scroll, and code page. Split out of the per-mode Control
  // panel so the two concerns don't clutter each other. Same state fields, same
  // optimistic + debounced PUT-on-change as before — this is a relocation.
  export let state: AppState | null = null;
  export let patch: (p: Partial<AppState>) => void;

  // Brightness has FOUR discrete levels (index 0..3); a stepped slider, NOT a %.
  const BRIGHTNESS_LABELS = ['MIN', 'MED', 'MED+', 'MAX'];
  const CODE_PAGES: { value: number; label: string }[] = [
    { value: 0, label: 'Default' },
    { value: 1, label: 'Japanese' },
    { value: 2, label: 'CP850' },
    { value: 3, label: 'CP852' },
    { value: 4, label: 'CP855' },
    { value: 5, label: 'CP857' },
  ];

  // Typed handlers. Svelte parses markup expressions with acorn (not TS), so no
  // casts/annotations can live in the template — keep all TS in here.
  function num(e: Event): number {
    return Number((e.target as HTMLInputElement | HTMLSelectElement).value);
  }
  function checked(e: Event): boolean {
    return (e.currentTarget as HTMLInputElement).checked;
  }
  function clampLevel(n: number): Brightness {
    return Math.max(0, Math.min(3, Math.round(n))) as Brightness;
  }
  const setBrightness = (e: Event) => patch({ brightness: clampLevel(num(e)) });
  const setBlank = (e: Event) => patch({ blank: checked(e) });
  const setScroll = (e: Event) => patch({ scroll: checked(e) });
  const setCodePage = (e: Event) => patch({ code_page: num(e) });
</script>

<section class="panel">
  <div class="panel__title">Display</div>

  {#if !state}
    <p class="loading">connecting to daemon…</p>
  {:else}
    <!-- Brightness -->
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

    <!-- Blank + hardware scroll -->
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
</style>
