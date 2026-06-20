<script lang="ts">
  import { postCommand } from '../api';

  let busy = '';
  let lastFired = '';

  async function fire(action: string, confirmMsg?: string): Promise<void> {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    busy = action;
    try {
      await postCommand(action);
      lastFired = action;
    } catch {
      lastFired = `${action} (failed)`;
    } finally {
      busy = '';
    }
  }
</script>

<section class="panel">
  <div class="panel__title">Commands</div>
  <div class="row">
    <button
      class="btn"
      disabled={busy !== ''}
      on:click={() => fire('self_test')}
    >
      Self-test
    </button>
    <button
      class="btn btn--danger"
      disabled={busy !== ''}
      on:click={() =>
        fire('reset', 'Reset the display? This reinitializes the panel.')}
    >
      Reset
    </button>
  </div>
  {#if lastFired}
    <p class="last">last → <span>{lastFired}</span></p>
  {/if}
  <p class="field__hint">
    Fire-once actions. The daemon runs each exactly once (nonce-guarded).
  </p>
</section>

<style>
  .last {
    margin: 12px 0 4px;
    font-size: 11px;
    color: var(--text-mute);
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .last span {
    color: var(--phosphor);
  }
</style>
