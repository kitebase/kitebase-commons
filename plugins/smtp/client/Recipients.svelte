<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Addresses of the record': 'Indirizzi del record',
    'Choose from the addresses of the record': 'Scegli fra gli indirizzi del record',
    'By function': 'Per funzione',
    'Main': 'Principale',
    'No address': 'Nessun indirizzo',
    'Use these': 'Usa questi',
    'Cancel': 'Annulla',
    'Loading...': 'Caricamento...',
  });

  /** The entries of a To field, split on the commas outside quotes and <>. */
  export function splitAddresses(text: string): string[] {
    const out: string[] = [];
    let current = '';
    let quoted = false;
    let angled = false;
    for (const ch of text) {
      if (ch === '"') quoted = !quoted;
      else if (ch === '<' && !quoted) angled = true;
      else if (ch === '>' && !quoted) angled = false;
      if (ch === ',' && !quoted && !angled) {
        if (current.trim()) out.push(current.trim());
        current = '';
      } else {
        current += ch;
      }
    }
    if (current.trim()) out.push(current.trim());
    return out;
  }

  /** The bare address of an entry: what is inside <>, or the entry. */
  export function bareAddress(entry: string): string {
    const m = entry.match(/<([^>]*)>\s*$/);
    return (m ? m[1] : entry).trim().toLowerCase();
  }
</script>

<script lang="ts">
  /**
   * The To field of a message. Registry ID: smtp.recipients.
   *
   * Written by hand like any text field; when the draft names a record
   * (`record: {model, id}`), a button opens its addresses (smtp_addresses):
   * the record's own and, where a plugin registers them, those of its
   * contacts with their functions. The ones already in the field come ticked,
   * and a button per function held ticks its holders: picking the functions
   * picks the people. Confirming rewrites the field with the ticked ones,
   * keeping what was typed that is none of the record's.
   */
  import { Dialog } from 'bits-ui';
  import { _ } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';
  import { errorText } from '$kitebase/api/envelope';
  import { syncStringState, dispatchEnter } from '$kitebase/components/widgets/widget.svelte.ts';
  import type { FormField } from '$kitebase/components/dataform.types';
  import { BookUser } from '@lucide/svelte';

  interface Address {
    model: string;
    id: unknown;
    name: string;
    email: string;
    functions: string[];
    note: string;
    main: boolean;
    to: string;
  }

  interface Props {
    value: unknown;
    onchange: (v: unknown) => void;
    onblur?: () => void;
    readonly?: boolean;
    record?: Record<string, unknown>;
    field: FormField;
  }

  let { value, onchange, onblur, readonly = false, record, field }: Props = $props();

  const text = syncStringState(() => value);

  const source = $derived.by(() => {
    const r = record?.record as { model?: string; id?: unknown } | undefined;
    return r?.model && r.id != null ? { model: r.model, id: r.id } : null;
  });

  let open = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let rows = $state<Address[]>([]);
  let ticked = $state<Record<string, boolean>>({});
  let functions = $state<{ value: string; label: string }[]>([]);
  let picked = $state<string[]>([]);

  function set(entered: string) {
    text.current = entered;
    onchange(entered === '' ? null : entered);
  }

  async function show() {
    if (!source) return;
    open = true;
    loading = true;
    error = null;
    const res = await api.endpoint<{ addresses: Address[]; functions: { value: string; label: string }[] }>(
      'smtp_addresses', source);
    loading = false;
    picked = [];
    if (res.status !== 'success' || !res.data) {
      error = errorText(res, _('No address'));
      rows = [];
      functions = [];
      return;
    }
    rows = res.data.addresses;
    functions = res.data.functions;
    const present = new Set(splitAddresses(text.current ?? '').map(bareAddress));
    ticked = Object.fromEntries(rows.map((r) => [r.email, present.has(r.email.toLowerCase())]));
  }

  /** Toggle a function: the ticked become the holders of the ones picked. */
  function pick(code: string) {
    picked = picked.includes(code) ? picked.filter((c) => c !== code) : [...picked, code];
    if (picked.length === 0) return;
    ticked = Object.fromEntries(rows.map((r) => [r.email, r.functions.some((f) => picked.includes(f))]));
  }

  function confirm() {
    const known = new Set(rows.map((r) => r.email.toLowerCase()));
    const typed = splitAddresses(text.current ?? '').filter((e) => !known.has(bareAddress(e)));
    set([...rows.filter((r) => ticked[r.email]).map((r) => r.to), ...typed].join(', '));
    open = false;
    onblur?.();
  }
</script>

{#if readonly}
  <span class="kb-recipients-ro">{text.current ?? ''}</span>
{:else}
  <div class="kb-recipients">
    <input
      type="text"
      class="input {field.error ? 'input-error' : ''}"
      value={text.current}
      oninput={(e) => set((e.target as HTMLInputElement).value)}
      onblur={() => onblur?.()}
      onkeydown={dispatchEnter}
      aria-label={field.label ?? field.name}
    />
    {#if source}
      <button type="button" class="kb-recipients-pick" onclick={show}
              title={_('Choose from the addresses of the record')}
              aria-label={_('Choose from the addresses of the record')}>
        <BookUser size={16} />
      </button>
    {/if}
  </div>
{/if}

<Dialog.Root bind:open>
  <Dialog.Portal>
    <Dialog.Overlay class="kb-recipients-overlay" />
    <Dialog.Content class="kb-recipients-dialog">
      <Dialog.Title class="kb-recipients-title">{_('Addresses of the record')}</Dialog.Title>
      <div class="kb-recipients-list">
        {#if loading}
          <p class="kb-recipients-note">{_('Loading...')}</p>
        {:else if error}
          <p class="kb-recipients-error">{error}</p>
        {:else if rows.length === 0}
          <p class="kb-recipients-note">{_('No address')}</p>
        {:else}
          {#if functions.length}
            <div class="kb-recipients-by">
              <span>{_('By function')}:</span>
              {#each functions as fn (fn.value)}
                <button type="button" class="kb-recipients-fn" class:on={picked.includes(fn.value)}
                        aria-pressed={picked.includes(fn.value)}
                        onclick={() => pick(fn.value)}>{fn.label}</button>
              {/each}
            </div>
          {/if}
          {#each rows as row (row.email)}
            <label class="kb-recipients-row">
              <input type="checkbox" bind:checked={ticked[row.email]} />
              <span class="kb-recipients-who">
                <span class="kb-recipients-name">{row.name || row.email}</span>
                {#if row.main}<span class="kb-recipients-badge">{_('Main')}</span>{/if}
                {#if row.note}<span class="kb-recipients-functions">{row.note}</span>{/if}
                <span class="kb-recipients-email">{row.email}</span>
              </span>
            </label>
          {/each}
        {/if}
      </div>
      <div class="kb-recipients-actions">
        <button type="button" class="btn btn-secondary" onclick={() => (open = false)}>{_('Cancel')}</button>
        <button type="button" class="btn btn-primary" onclick={confirm}
                disabled={loading || rows.length === 0}>{_('Use these')}</button>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<style>
  .kb-recipients {
    display: flex;
    gap: 0.25rem;
    align-items: center;
  }
  .kb-recipients input { flex: 1; min-width: 0; }
  .kb-recipients-pick {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 2.25rem;
    padding: 0 0.5rem;
    border: 1px solid var(--kb-border-input);
    border-radius: 0.375rem;
    color: var(--kb-text-subtle);
  }
  .kb-recipients-pick:hover { background: var(--kb-surface-hover); color: var(--kb-text); }
  .kb-recipients-ro {
    display: block;
    padding: 0.4rem 0;
    font-size: 0.875rem;
    color: var(--kb-text);
    min-height: 2rem;
  }
  /* Plain CSS: a plugin's classes are not among the ones Tailwind scans */
  :global(.kb-recipients-overlay) {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: rgb(0 0 0 / 0.4);
  }
  :global(.kb-recipients-dialog) {
    position: fixed;
    top: 50%;
    left: 50%;
    z-index: 50;
    display: flex;
    flex-direction: column;
    width: min(30rem, calc(100vw - 2rem));
    max-height: calc(100vh - 4rem);
    transform: translate(-50%, -50%);
    border: 1px solid var(--kb-border);
    border-radius: 0.75rem;
    background: var(--kb-bg);
    color: var(--kb-text);
    box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
  }
  :global(.kb-recipients-dialog:focus) { outline: none; }
  :global(.kb-recipients-title) {
    padding: 1rem 1.25rem 0.5rem;
    font-size: 1rem;
    font-weight: 600;
  }
  .kb-recipients-list {
    overflow: auto;
    padding: 0 1.25rem;
  }
  .kb-recipients-by {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
    align-items: center;
    padding: 0.25rem 0 0.5rem;
    font-size: 0.8rem;
    color: var(--kb-text-subtle);
  }
  .kb-recipients-fn {
    padding: 0.125rem 0.5rem;
    border: 1px solid var(--kb-border-input);
    border-radius: 999px;
    color: var(--kb-text);
  }
  .kb-recipients-fn:hover { background: var(--kb-surface-hover); }
  .kb-recipients-fn.on {
    border-color: var(--kb-accent-border);
    background: var(--kb-accent-light);
    color: var(--kb-accent);
  }
  .kb-recipients-row {
    display: flex;
    gap: 0.625rem;
    align-items: flex-start;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--kb-border);
    cursor: pointer;
  }
  .kb-recipients-row input { margin-top: 0.2rem; }
  .kb-recipients-who {
    display: flex;
    flex-wrap: wrap;
    gap: 0 0.5rem;
    align-items: baseline;
    font-size: 0.875rem;
  }
  .kb-recipients-name { font-weight: 500; }
  .kb-recipients-badge {
    padding: 0 0.375rem;
    border-radius: 0.25rem;
    background: var(--kb-surface);
    border: 1px solid var(--kb-border);
    font-size: 0.75rem;
  }
  .kb-recipients-functions { color: var(--kb-text-subtle); font-size: 0.8rem; }
  .kb-recipients-email { flex-basis: 100%; color: var(--kb-text-subtle); font-size: 0.8rem; }
  .kb-recipients-note { padding: 0.5rem 0; color: var(--kb-text-subtle); font-size: 0.875rem; }
  .kb-recipients-error { padding: 0.5rem 0; color: var(--kb-danger); font-size: 0.875rem; }
  .kb-recipients-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding: 0.75rem 1.25rem 1rem;
  }
</style>
