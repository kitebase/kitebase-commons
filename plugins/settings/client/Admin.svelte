<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Group': 'Gruppo',
    'Setting': 'Parametro',
    'Key': 'Chiave',
    'Value': 'Valore',
    'Default': 'Default',
    'State': 'Stato',
    'Delete orphans': 'Elimina orfani',
    'Pick a setting to change its group.': 'Scegli un parametro per modificare il suo gruppo.',
    'An orphan is a row no plugin declares any more: it can only be deleted.':
      'Un orfano è una riga che nessun plugin dichiara più: si può solo eliminare.',
  });
</script>

<script lang="ts">
  /**
   * Every setting of the application, for the administrator. Registry ID:
   * settings.admin.
   *
   * On the left all the items of all the groups, and the rows no catalog
   * declares any more (orphans), with their state: default, set, orphan. A
   * click opens the form of the item's group on the right, the same form a
   * menu opens; the command deletes the orphan rows, the ticked ones or all.
   */
  import { _ } from '$kitebase/i18n';
  import DataView from '$kitebase/components/DataView.svelte';
  import type { ViewDescriptor } from '$kitebase/components/dataview.types';
  import Group from './Group.svelte';

  interface Row {
    id: string;
    group: string;
    state: 'default' | 'set' | 'orphan';
    [key: string]: unknown;
  }

  let selected = $state<Row | null>(null);
  // The list is read again after a change made in the form.
  let generation = $state(0);

  const view = {
    type: 'table',
    source: { endpoint: 'settings_list' },
    columns: [
      { field: 'group_label', title: _('Group') },
      { field: 'label', title: _('Setting') },
      { field: 'id', title: _('Key') },
      { field: 'value', title: _('Value') },
      { field: 'default', title: _('Default') },
      { field: 'state_label', title: _('State') },
    ],
    // Rows of an endpoint, not of a table: ticks for the command, no add or delete.
    navigator: {
      mode: 'readonly',
      show: ['select'],
      commands: [{ id: 'drop_orphans', label: _('Delete orphans'),
                   endpoint: 'settings_drop_orphans', scope: 'global' }],
    },
  } as unknown as ViewDescriptor;

  function onEvent(name: string, data: unknown) {
    if (name === 'row_click') selected = data as Row;
  }
</script>

<div class="settings-admin">
  <div class="list">
    {#key generation}
      <DataView {view} {onEvent} />
    {/key}
  </div>
  <div class="side">
    {#if selected && selected.state !== 'orphan'}
      <Group group={selected.group} onchange={() => (generation += 1)} />
    {:else if selected}
      <p class="note">{_('An orphan is a row no plugin declares any more: it can only be deleted.')}</p>
    {:else}
      <p class="note">{_('Pick a setting to change its group.')}</p>
    {/if}
  </div>
</div>

<style>
  .settings-admin {
    display: grid;
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    gap: 1rem;
    height: 100%;
    min-height: 0;
  }
  .list {
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .side {
    min-height: 0;
    overflow: auto;
    border-left: 1px solid var(--kb-border);
  }
  .note {
    padding: 1rem;
    font-size: 0.85rem;
    color: var(--kb-text-subtle);
  }
</style>
