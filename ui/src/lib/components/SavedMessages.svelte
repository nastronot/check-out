<script lang="ts">
  import { deleteMessage, recallMessage, saveMessage } from '../api';
  import { appState, applyState, library, refreshLibrary } from '../stores';
  import type { LibraryMessage } from '../types';

  let busy = '';

  async function saveCurrent(): Promise<void> {
    const s = $appState;
    if (!s) return;
    const name = window.prompt('Save current message as:')?.trim();
    if (!name) return;
    busy = 'save';
    try {
      // Capture the full composable state, incl. the glyphs this message uses.
      await saveMessage({
        name,
        message: s.message,
        mode: s.mode === 'ticker' ? 'ticker' : 'message',
        align_top: s.align_top,
        align_bottom: s.align_bottom,
        brightness: s.brightness,
        glyphs: s.glyphs,
      });
      await refreshLibrary();
    } finally {
      busy = '';
    }
  }

  async function recall(item: LibraryMessage): Promise<void> {
    busy = item.id;
    try {
      applyState(await recallMessage(item.id));
    } finally {
      busy = '';
    }
  }

  async function remove(item: LibraryMessage): Promise<void> {
    if (!window.confirm(`Delete saved message "${item.name}"?`)) return;
    busy = item.id;
    try {
      await deleteMessage(item.id);
      await refreshLibrary();
    } finally {
      busy = '';
    }
  }

  function preview(m: LibraryMessage): string {
    return (m.message || '').replace(/\n/g, ' ⏎ ').slice(0, 28) || '(empty)';
  }
</script>

<section class="panel">
  <div class="panel__title">
    Saved messages
    <button class="btn btn--mini" disabled={busy !== '' || !$appState} on:click={saveCurrent}>
      Save current
    </button>
  </div>

  {#if $library.messages.length === 0}
    <p class="field__hint">No saved messages yet. Compose one, then “Save current”.</p>
  {:else}
    <ul class="list">
      {#each $library.messages as m (m.id)}
        <li class="item">
          <div class="item__main">
            <span class="item__name">{m.name}</span>
            <span class="item__preview">{preview(m)}</span>
            <span class="item__meta">{m.mode}</span>
          </div>
          <div class="item__actions">
            <button class="btn btn--mini" disabled={busy !== ''} on:click={() => recall(m)}>
              Recall
            </button>
            <button class="btn btn--mini btn--danger" disabled={busy !== ''} on:click={() => remove(m)}>
              ✕
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .panel__title {
    justify-content: space-between;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 10px;
    background: #04090a;
    border: 1px solid var(--bezel);
    border-radius: 5px;
  }

  .item__main {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
  }

  .item__name {
    color: var(--phosphor-ink);
    font-size: 13px;
  }

  .item__preview {
    color: var(--text-mute);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .item__meta {
    font-size: 9px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-faint);
  }

  .item__actions {
    display: flex;
    gap: 6px;
    flex: none;
  }

  .btn--mini {
    padding: 5px 10px;
    font-size: 11px;
  }
</style>
