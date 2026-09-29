<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { getBumpbar, putBumpbarMap, resetBumpbarMap } from '../api';
  import {
    actionLabel,
    groupActions,
    isFlashing,
    type BumpBar,
    type BumpButton,
    type BumpMap,
    type Layer,
  } from '../bumpbar';

  // The bump bar page: a drawing of the real pad with each key's two actions,
  // a Key panel to remap the selected key, and the service's Device readout.
  // The web only WRITES bumpbar.json; the service picks it up on the next press.
  let data: BumpBar | null = null;
  let loadError = '';
  let saveError = '';
  let selected = 'next';
  let now = Date.now();
  let saving = 0; // in-flight map writes: a poll must not overwrite them

  async function poll(): Promise<void> {
    try {
      const fresh = await getBumpbar();
      data = saving && data ? { ...fresh, map: data.map } : fresh;
      loadError = '';
    } catch (e) {
      loadError = String(e);
    }
  }

  let pollTimer: ReturnType<typeof setInterval>;
  let clockTimer: ReturnType<typeof setInterval>;
  onMount(() => {
    void poll();
    pollTimer = setInterval(() => void poll(), 500);
    clockTimer = setInterval(() => (now = Date.now()), 100);
  });
  onDestroy(() => {
    clearInterval(pollTimer);
    clearInterval(clockTimer);
  });

  async function saveMap(next: BumpMap): Promise<void> {
    if (!data) return;
    data = { ...data, map: next };
    saving += 1;
    try {
      const stored = await putBumpbarMap(next);
      if (data) data = { ...data, map: stored };
      saveError = '';
    } catch (e) {
      saveError = String(e);
    } finally {
      saving -= 1;
    }
    if (saveError) await poll();
  }

  function setAction(layer: Layer, button: string, e: Event): void {
    if (!data) return;
    const value = (e.currentTarget as HTMLSelectElement).value;
    void saveMap({ ...data.map, [layer]: { ...data.map[layer], [button]: value } });
  }

  async function resetMap(): Promise<void> {
    if (!data) return;
    saving += 1;
    try {
      const stored = await resetBumpbarMap();
      if (data) data = { ...data, map: stored };
      saveError = '';
    } catch (e) {
      saveError = String(e);
    } finally {
      saving -= 1;
    }
  }

  function legendOf(b: BumpButton): string {
    return b.legend || 'SHIFT';
  }

  function hintOf(id: string): string {
    return data?.actions.find((a) => a.id === id)?.hint ?? '';
  }

  function ago(at: string, t: number): string {
    const s = Math.max(0, Math.round((t - Date.parse(at)) / 1000));
    if (Number.isNaN(s)) return '';
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
  }

  $: status = data?.status ?? null;
  $: press = status?.last_press ?? null;
  $: hit = press && isFlashing(press.at, now) ? press.button : '';
  $: shiftHeld = !!status?.connected && status?.layer === 'shift';
  $: groups = groupActions(data?.actions ?? []);
  $: current = data?.buttons.find((b) => b.id === selected) ?? null;
  $: isShift = !!data && selected === data.shift;
  $: connected = !!data?.alive && !!status?.connected;
  $: errorText = saveError || data?.map_error || status?.error || '';
  $: pressLegend = press
    ? legendOf(data?.buttons.find((b) => b.id === press?.button) ?? { id: '', legend: press.button, color: 'grey' })
    : '';
</script>

<main class="bb">
  <section class="panel pad-panel">
    <div class="panel__title">
      Pad
      <button class="btn" on:click={resetMap} disabled={!data}>Defaults</button>
    </div>

    {#if !data}
      <p class="muted">{loadError ? `web API: ${loadError}` : 'loading…'}</p>
    {:else}
      <!-- The real bar: brushed steel plate, 2×5 keys in their cap colours. -->
      <div class="plate">
        <div class="keys">
          {#each data.buttons as b (b.id)}
            <button
              class="key key--{b.color}"
              class:key--hit={hit === b.id || (b.id === data.shift && shiftHeld)}
              aria-pressed={selected === b.id}
              on:click={() => (selected = b.id)}
            >
              <span class="key__legend" class:key__legend--shift={!b.legend}>{b.legend || '⇧'}</span>
              <span class="key__acts">
                {#if b.id === data.shift}
                  <span class="key__act">shift</span>
                  <span class="key__act key__act--alt">hold</span>
                {:else}
                  <span class="key__act">{actionLabel(data.actions, data.map.tap[b.id])}</span>
                  <span class="key__act key__act--alt">⇧ {actionLabel(data.actions, data.map.shift[b.id])}</span>
                {/if}
              </span>
            </button>
          {/each}
        </div>
        <span
          class="plate__led"
          class:plate__led--idle={connected && !hit}
          class:plate__led--hit={connected && !!hit}
          title={connected ? 'bar connected' : 'bar not connected'}
        ></span>
      </div>
      <p class="field__hint pad-hint">Click a key to remap it. Hold the grey key for the ⇧ action.</p>
    {/if}
  </section>

  <div class="side">
    <section class="panel">
      <div class="panel__title">Key · {current ? legendOf(current) : '—'}</div>
      {#if data && current}
        {#if isShift}
          <p class="field__hint">
            The grey key is the shift. Hold it and every other key does its ⇧ action.
            It can't be remapped.
          </p>
        {:else}
          {#each data.layers as layer (layer)}
            <div class="field">
              <label class="field__label" for="act-{layer}">
                {layer === 'tap' ? 'Tap' : 'With ⇧ held'}
              </label>
              <select
                id="act-{layer}"
                value={data.map[layer][current.id]}
                on:change={(e) => current && setAction(layer, current.id, e)}
              >
                <optgroup label="check-out">
                  {#each groups.checkout as a (a.id)}
                    <option value={a.id}>{a.label}</option>
                  {/each}
                </optgroup>
                <optgroup label="system">
                  {#each groups.system as a (a.id)}
                    <option value={a.id}>{a.label}</option>
                  {/each}
                </optgroup>
              </select>
              <span class="field__hint">{hintOf(data.map[layer][current.id])}</span>
            </div>
          {/each}
        {/if}
      {:else}
        <p class="muted">loading…</p>
      {/if}
    </section>

    <section class="panel">
      <div class="panel__title">Device</div>
      {#if data && !data.installed}
        <p class="field__hint">
          No bump bar service has run on this machine. The map still saves; it
          takes effect wherever <code>checkout-bumpbar</code> runs.
        </p>
      {:else if data}
        <div class="rows">
          <div class="ctl-row">
            <span class="ctl-row__name">Service</span>
            <span class="led" class:led--on={data.alive} class:led--dead={!data.alive}></span>
            <span class="val">{data.alive ? 'live' : 'stopped'}</span>
          </div>
          <div class="ctl-row">
            <span class="ctl-row__name">Bar</span>
            <span class="led" class:led--on={connected} class:led--dead={!connected}></span>
            <span class="val">{connected ? 'connected · grabbed' : 'unplugged'}</span>
          </div>
          {#if status?.device}
            <div class="ctl-row">
              <span class="ctl-row__name">Node</span>
              <code class="node" title={status.device}>{status.device}</code>
            </div>
          {/if}
          <div class="ctl-row">
            <span class="ctl-row__name">Last</span>
            {#if press}
              <span class="val">
                {press.layer === 'shift' ? '⇧ ' : ''}{pressLegend} →
                <span class="readout">{actionLabel(data.actions, press.action)}</span>
              </span>
              <span class="tag">{ago(press.at, now)}</span>
            {:else}
              <span class="val muted">no press yet</span>
            {/if}
          </div>
        </div>
      {/if}
      {#if errorText}
        <p class="err">{errorText}</p>
      {/if}
    </section>
  </div>
</main>

<style>
  .bb {
    display: grid;
    grid-template-columns: 1.25fr 1fr;
    gap: 20px;
    align-items: start;
  }

  /* Grid children may shrink below their content (the long device path), or
     the page overflows sideways on a phone. */
  .bb > * {
    min-width: 0;
  }

  .side {
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-width: 0;
  }

  .muted {
    color: var(--text-faint);
    font-size: 12px;
  }

  /* --- the plate: brushed stainless, like the real bar -------------------- */
  .plate {
    position: relative;
    padding: 22px 22px 34px;
    border-radius: 8px;
    background:
      repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.035) 0 1px, transparent 1px 3px),
      linear-gradient(160deg, #9aa0a2, #6f7577 45%, #8b9193 70%, #5e6466);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.35),
      inset 0 -2px 6px rgba(0, 0, 0, 0.35),
      0 4px 14px rgba(0, 0, 0, 0.6);
  }

  .keys {
    display: grid;
    /* minmax(0, …): long action labels ellipsise instead of widening a key. */
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 12px 14px;
  }

  .key {
    --cap: #d9d9d4;
    --ink: #1b1d1e;
    appearance: none;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 8px;
    min-height: 84px;
    padding: 9px 10px 8px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    text-align: center;
    font-family: var(--mono);
    color: var(--ink);
    background: linear-gradient(180deg, color-mix(in srgb, var(--cap) 82%, white), var(--cap) 55%, color-mix(in srgb, var(--cap) 80%, black));
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.45),
      0 3px 0 color-mix(in srgb, var(--cap) 45%, black),
      0 5px 8px rgba(0, 0, 0, 0.45);
    transition: transform 0.06s, box-shadow 0.12s, filter 0.12s;
  }

  .key--red { --cap: #c8322b; --ink: #fff4f2; }
  .key--green { --cap: #2f9e4f; --ink: #f2fff5; }
  .key--grey { --cap: #d9d9d4; --ink: #1b1d1e; }
  .key--blue { --cap: #3d7fd1; --ink: #f2f7ff; }
  .key--dark { --cap: #55595c; --ink: #e6e8e8; }

  .key:hover {
    filter: brightness(1.06);
  }

  .key[aria-pressed='true'] {
    outline: 2px solid var(--phosphor);
    outline-offset: 3px;
  }

  /* A press on the REAL bar lights the drawn key for FLASH_MS. */
  .key--hit {
    transform: translateY(2px);
    filter: brightness(1.2);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.45),
      0 1px 0 color-mix(in srgb, var(--cap) 45%, black),
      0 0 16px var(--phosphor);
  }

  .key__legend {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.06em;
    line-height: 1.15;
  }

  .key__legend--shift {
    font-size: 20px;
    line-height: 0.8;
  }

  /* The two actions, in the display's own phosphor-on-black voice. */
  .key__acts {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 4px 6px;
    border-radius: 3px;
    background: #04090a;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.8);
  }

  .key__act {
    font-size: 10px;
    letter-spacing: 0.04em;
    color: var(--phosphor);
    text-shadow: 0 0 6px var(--phosphor-deep);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .key__act--alt {
    color: var(--phosphor-dim);
    text-shadow: none;
  }

  /* The bar's status LED: green idle, red while a key is down, dark when off. */
  .plate__led {
    position: absolute;
    left: 50%;
    bottom: 12px;
    width: 8px;
    height: 8px;
    margin-left: -4px;
    border-radius: 50%;
    background: #2a2f30;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.7);
  }

  .plate__led--idle {
    background: #43e06a;
    box-shadow: 0 0 8px #43e06a;
  }

  .plate__led--hit {
    background: #ff4b3a;
    box-shadow: 0 0 8px #ff4b3a;
  }

  .pad-hint {
    display: block;
    margin-top: 12px;
  }

  /* --- device readout ------------------------------------------------------ */
  .rows {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .val {
    font-size: 12px;
    color: var(--text);
  }

  .node {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .err {
    margin: 10px 0 0;
    font-size: 11px;
    color: var(--amber-warn);
  }

  select {
    width: 100%;
  }

  @media (max-width: 860px) {
    .bb {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 600px) {
    .plate {
      padding: 14px 12px 30px;
    }

    .keys {
      gap: 10px;
    }
  }
</style>
