<script lang="ts">
  import type { AppState, Animation, Brightness, Mode } from '../types';

  export let state: AppState | null = null;
  export let patch: (p: Partial<AppState>) => void;

  const MODES: Mode[] = ['clock', 'message', 'ticker'];
  const ANIMATIONS: Animation[] = ['none', 'flash', 'blink'];
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

  $: budget = messageDraft.length;
  $: overBudget = budget > 40;

  function num(e: Event): number {
    return Number((e.target as HTMLInputElement | HTMLSelectElement).value);
  }
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
            on:click={() => patch({ mode: m })}>{m}</button
          >
        {/each}
      </div>
    </div>

    <!-- Message -->
    <div class="field">
      <span class="field__label">
        Message
        <span class:over={overBudget}>{budget}/40</span>
      </span>
      <input
        type="text"
        bind:value={messageDraft}
        on:input={onMessageInput}
        placeholder="drives message / ticker"
        spellcheck="false"
      />
      <span class="field__hint">
        Use <code>{'{g0}'}</code>…<code>{'{g8}'}</code> to drop in custom glyphs
        (light up once defined). Newline splits the two lines in message mode.
      </span>
    </div>

    <!-- Brightness + scroll -->
    <div class="field">
      <span class="field__label">Brightness</span>
      <div class="seg">
        {#each ['dim', 'bright'] as b}
          <button
            type="button"
            aria-pressed={state.brightness === b}
            on:click={() => patch({ brightness: b as Brightness })}>{b}</button
          >
        {/each}
      </div>
    </div>

    <div class="row switches">
      <label class="switch">
        <input
          type="checkbox"
          checked={state.blank}
          on:change={(e) => patch({ blank: e.currentTarget.checked })}
        />
        <span class="switch__track"></span>
        <span class="switch__label">Blank</span>
      </label>

      <label class="switch" title="Hardware vertical scroll — for marquee effects">
        <input
          type="checkbox"
          checked={state.scroll}
          on:change={(e) => patch({ scroll: e.currentTarget.checked })}
        />
        <span class="switch__track"></span>
        <span class="switch__label">HW scroll</span>
      </label>
    </div>

    <!-- Code page -->
    <div class="field">
      <span class="field__label">Code page</span>
      <select
        value={state.code_page}
        on:change={(e) => patch({ code_page: num(e) })}
      >
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
            on:click={() => patch({ animation: a })}>{a}</button
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
              on:change={(e) =>
                patch({
                  animation_params: {
                    on_ms: num(e),
                    off_ms: state?.animation_params.off_ms ?? 500,
                  },
                })}
            /> ms</label>
          <label class="field__hint">off
            <input
              type="number"
              min="50"
              step="50"
              value={state.animation_params.off_ms}
              on:change={(e) =>
                patch({
                  animation_params: {
                    on_ms: state?.animation_params.on_ms ?? 500,
                    off_ms: num(e),
                  },
                })}
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
            on:change={(e) => patch({ scroll_speed_ms: num(e) })}
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
</style>
