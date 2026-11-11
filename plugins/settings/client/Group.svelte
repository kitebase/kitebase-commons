<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Loading...': 'Caricamento...',
    'Set': 'Impostato',
    'default': 'default',
    'follows the default': 'segue il default',
    'Restore': 'Ripristina',
    'Restore the default of a set setting': 'Ripristina il default di un parametro impostato',
  });
</script>

<script lang="ts">
  /**
   * The form of a group of settings. Registry ID: settings.group, a page of
   * `type: plugin` with `props: { group: <name> }`.
   *
   * One form, one field per item of the catalog (get_settings), in the order
   * declared, the widget from its type. Under each field, always: its help and
   * its state, set (with the default it departs from) or following the default
   * (help_display: inline). The form loads and saves through the endpoints
   * (settings_values, set_settings), and the server writes a row only for a
   * value the user touched. "Restore", in the toolbar, lists the set items: one picked
   * follows the default again.
   */
  import { _ } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';
  import { errorText } from '$kitebase/api/envelope';
  import DataForm from '$kitebase/components/DataForm.svelte';
  import type { FormDescriptor } from '$kitebase/components/dataform.types';

  interface Item {
    key: string;
    name: string;
    type: string;
    label: string;
    help: string | null;
    default: unknown;
    value: unknown;
    set: boolean;
  }

  interface Group {
    group: string;
    label: string;
    help: string | null;
    items: Item[];
  }

  interface Props {
    group: string;
    /** Called after a save or a restore: the administrator's list refreshes. */
    onchange?: () => void;
  }

  let { group, onchange }: Props = $props();

  let meta = $state<Group | null>(null);
  let error = $state<string | null>(null);
  let menuOpen = $state(false);
  // A restore changes the values under the form: it is drawn again from them.
  let generation = $state(0);

  async function load(name: string) {
    const res = await api.endpoint('get_settings', { group: name });
    if (res.status === 'success') {
      meta = res.data as Group;
      error = null;
    } else {
      meta = null;
      error = errorText(res, 'Error');
    }
  }

  $effect(() => {
    void load(group);
  });

  const shown = (v: unknown) =>
    v === null || v === undefined || v === '' ? '-'
      : typeof v === 'object' ? JSON.stringify(v) : String(v);

  function stateLine(item: Item): string {
    return item.set
      ? `${_('Set')} (${_('default')}: ${shown(item.default)})`
      : _('follows the default');
  }

  const view = $derived<FormDescriptor | null>(meta && {
    type: 'form',
    source: { endpoint: 'settings_values', save_endpoint: 'set_settings', pass: { group } },
    fields: meta.items.map((i) => ({
      name: i.name, label: i.label, type: i.type,
      help: i.help ? `${i.help}\n${stateLine(i)}` : stateLine(i),
    })),
    policy: { editable: true },
    // A page of settings is its explanation: each help in view, under its field.
    help_display: 'inline',
    actions: { toolbar: ['save', 'cancel'] },
  } as FormDescriptor);

  const setItems = $derived(meta?.items.filter((i) => i.set) ?? []);

  async function restore(item: Item) {
    menuOpen = false;
    const res = await api.endpoint('set_settings', { group, reset: [item.name] });
    if (res.status !== 'success') {
      error = errorText(res, 'Error');
      return;
    }
    await load(group);
    generation += 1;
    onchange?.();
  }

  async function saved() {
    await load(group);
    onchange?.();
  }
</script>

<svelte:window onclick={() => (menuOpen = false)} />

<div class="settings-group">
  {#if error}
    <p class="note error">{error}</p>
  {:else if !meta || !view}
    <p class="note">{_('Loading...')}</p>
  {:else}
    <header>
      <h2>{meta.label}</h2>
      {#if meta.help}<p class="note">{meta.help}</p>{/if}
    </header>

    {#key `${group}:${generation}`}
      <div class="form">
        <DataForm {view} onEvent={(name) => { if (name === 'form_save') void saved(); }}>
          {#snippet toolbarExtra()}
            {#if setItems.length}
              <div class="restore">
                <button type="button" title={_('Restore the default of a set setting')}
                  onclick={(e) => { e.stopPropagation(); menuOpen = !menuOpen; }}>
                  {_('Restore')}
                </button>
                {#if menuOpen}
                  <ul role="menu">
                    {#each setItems as item (item.key)}
                      <li>
                        <button type="button" role="menuitem"
                          onclick={(e) => { e.stopPropagation(); void restore(item); }}>
                          {item.label} <span class="default">({shown(item.default)})</span>
                        </button>
                      </li>
                    {/each}
                  </ul>
                {/if}
              </div>
            {/if}
          {/snippet}
        </DataForm>
      </div>
    {/key}
  {/if}
</div>

<style>
  .settings-group {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    color: var(--kb-text);
  }
  h2 {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
  }
  .note {
    margin: 0;
    font-size: 0.85rem;
    color: var(--kb-text-subtle);
  }
  .note.error {
    color: var(--kb-danger);
  }
  .form {
    border: 1px solid var(--kb-border);
    border-radius: 0.375rem;
    background: var(--kb-surface);
  }
  .restore {
    position: relative;
  }
  .restore > button {
    border: 1px solid var(--kb-border-input);
    border-radius: 0.25rem;
    padding: 0.15rem 0.6rem;
    font-size: 0.85rem;
    background: var(--kb-bg);
    color: var(--kb-text);
    cursor: pointer;
  }
  .restore > button:hover {
    background: var(--kb-surface-hover);
  }
  ul {
    position: absolute;
    right: 0;
    top: calc(100% + 0.25rem);
    z-index: 20;
    min-width: 14rem;
    margin: 0;
    padding: 0.25rem 0;
    list-style: none;
    border: 1px solid var(--kb-border);
    border-radius: 0.375rem;
    background: var(--kb-bg);
    box-shadow: 0 4px 12px rgb(0 0 0 / 0.08);
  }
  li button {
    display: block;
    width: 100%;
    padding: 0.3rem 0.75rem;
    border: 0;
    background: none;
    text-align: left;
    font-size: 0.85rem;
    color: var(--kb-text);
    cursor: pointer;
  }
  li button:hover {
    background: var(--kb-surface-hover);
  }
  .default {
    color: var(--kb-text-subtle);
  }
</style>
