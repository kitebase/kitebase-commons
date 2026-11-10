<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Table': 'Tabella',
    'Name': 'Nome',
    'Plugin': 'Plugin',
    'Kind': 'Tipo',
  });
</script>

<script lang="ts">
  /**
   * Every table the user may read, for maintenance. Registry ID: tables.browser.
   *
   * A double click or Enter on a row opens the table's generated list on the
   * stack, and from there its generated form: columns, filters, the rule editor.
   * What can be written is decided by each table's grants, as everywhere.
   */
  import { getContext } from 'svelte';
  import { _ } from '$kitebase/i18n';
  import DataView from '$kitebase/components/DataView.svelte';
  import PanelPage from '$kitebase/components/PanelPage.svelte';
  import { stack as globalStack, type StackInstance } from '$kitebase/stack/stack.svelte';
  import type { ViewDescriptor } from '$kitebase/components/dataview.types';

  const stack = getContext<StackInstance>('kb:stack') ?? globalStack;

  const view = {
    type: 'table',
    source: { endpoint: 'tables_list' },
    columns: [
      { field: 'label', title: _('Table') },
      { field: 'id', title: _('Name') },
      { field: 'table', title: 'SQL' },
      { field: 'plugin', title: _('Plugin') },
      { field: 'kind', title: _('Kind') },
    ],
    // Rows of an endpoint, not of a table: nothing to add or delete here.
    navigator: { mode: 'readonly' },
  } as unknown as ViewDescriptor;

  function onEvent(name: string, data: unknown) {
    if (name !== 'row_dblclick' && name !== 'row_accept') return;
    const page = (data as { page?: string } | null)?.page;
    if (page) stack.push(PanelPage, { panelId: page });
  }
</script>

<div class="tables-browser">
  <DataView {view} {onEvent} />
</div>

<style>
  .tables-browser {
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
</style>
