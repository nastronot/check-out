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

<!-- Self-test / Reset as small buttons in the Control panel's header: rarely
     used, so they take no space of their own. A failure shows as a red outline. -->
<span class="cmds">
  <button
    class="btn"
    class:btn--failed={lastFired.endsWith('(failed)')}
    disabled={busy !== ''}
    title="Run the display's built-in self-test"
    on:click={() => fire('self_test')}
  >
    Self-test
  </button>
  <button
    class="btn btn--danger"
    disabled={busy !== ''}
    title="Reinitialize the display"
    on:click={() => fire('reset', 'Reset the display? This reinitializes the panel.')}
  >
    Reset
  </button>
</span>

<style>
  .cmds {
    display: flex;
    gap: 6px;
    margin-left: auto;
  }

  .cmds .btn {
    margin-left: 0;
  }

  .btn--failed {
    border-color: var(--red-dead);
  }
</style>
