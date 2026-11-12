<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Attach a file': 'Allega un file',
    'Remove': 'Togli',
    'Uploading...': 'Caricamento...',
  });
</script>

<script lang="ts">
  /**
   * The files of a message being written. Registry ID: smtp.attachments, the
   * widget of the compose form's `attachments` field.
   *
   * A file is uploaded as soon as it is chosen (smtp_attach, the upload route)
   * and the field keeps what the server answers, `{ref, name}`: the message
   * sends the references, and the server lets a message carry only the files
   * its user uploaded. Removing one takes it off the message; the staged file
   * is the outbox's to clean.
   */
  import { _ } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';
  import { errorText } from '$kitebase/api/envelope';
  import { Paperclip, X } from '@lucide/svelte';

  interface Staged {
    ref: string;
    name: string;
  }

  interface Props {
    value: unknown;
    onchange: (v: unknown) => void;
    onblur?: () => void;
    readonly?: boolean;
  }

  let { value, onchange, onblur, readonly = false }: Props = $props();

  let input: HTMLInputElement;
  let uploading = $state(0);
  let error = $state<string | null>(null);

  const files = $derived(Array.isArray(value) ? (value as Staged[]) : []);

  async function add(e: Event) {
    const chosen = Array.from((e.target as HTMLInputElement).files ?? []);
    (e.target as HTMLInputElement).value = '';
    error = null;
    let current = files;
    for (const file of chosen) {
      uploading++;
      const res = await api.sendFile<Staged>('smtp_attach', {}, file);
      uploading--;
      if (res.status === 'success' && res.data) {
        current = [...current, res.data];
        onchange(current);
      } else {
        error = `${file.name}: ${errorText(res, _('Upload failed'))}`;
      }
    }
    onblur?.();
  }

  function remove(i: number) {
    onchange(files.filter((_f, j) => j !== i));
    onblur?.();
  }
</script>

<div class="kb-attachments">
  {#each files as file, i (file.ref)}
    <span class="kb-attachment">
      <Paperclip size={13} />
      {file.name}
      {#if !readonly}
        <button type="button" title={_('Remove')} aria-label={_('Remove')}
                onclick={() => remove(i)}><X size={13} /></button>
      {/if}
    </span>
  {/each}
  {#if !readonly}
    <button type="button" class="kb-attach" onclick={() => input.click()}>
      + {_('Attach a file')}
    </button>
    <input bind:this={input} type="file" multiple hidden onchange={add} />
  {/if}
  {#if uploading}
    <span class="kb-attach-note">{_('Uploading...')}</span>
  {/if}
  {#if error}
    <span class="kb-attach-error">{error}</span>
  {/if}
</div>

<style>
  .kb-attachments {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem;
    min-height: 2.25rem;
  }
  .kb-attachment {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
    background: var(--kb-surface-subtle);
    border: 1px solid var(--kb-border);
    color: var(--kb-text);
    font-size: 0.875rem;
  }
  .kb-attachment button {
    display: inline-flex;
    color: var(--kb-text-subtle);
  }
  .kb-attachment button:hover { color: var(--kb-danger); }
  .kb-attach {
    padding: 0.125rem 0.5rem;
    border: 1px dashed var(--kb-border-input);
    border-radius: 0.25rem;
    color: var(--kb-text-subtle);
    font-size: 0.875rem;
  }
  .kb-attach:hover { background: var(--kb-surface-hover); }
  .kb-attach-note { color: var(--kb-text-subtle); font-size: 0.8rem; }
  .kb-attach-error { color: var(--kb-danger); font-size: 0.8rem; }
</style>
