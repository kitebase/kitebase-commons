<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'State': 'Stato',
    'Row': 'Riga',
    'What differs': 'Cosa cambia',
    'Show equal rows': 'Mostra le righe uguali',
    'Add the new rows ticked': 'Aggiungi le nuove spuntate',
    'Tick the new rows to add them; open a row the table has to change it by hand.':
      'Spunta le righe nuove per aggiungerle; apri una riga della tabella per cambiarla a mano.',
    '{n} equal': '{n} uguali',
    '{n} different': '{n} diverse',
    '{n} new': '{n} nuove',
    '{n} only in the table': '{n} solo nella tabella',
    '{n} ambiguous': '{n} ambigue',
    '{n} ticked are not new: left alone': '{n} spuntate non sono nuove: lasciate stare',
  });
</script>

<script lang="ts">
  /**
   * A table against a seed set or a file. Registry ID: tables.seedcompare.
   *
   * Opened by the browser's command, with `{table, set}`, or with `{table,
   * rows, source}` for a file the user uploaded: those rows go back with every
   * call, since the server keeps nothing of the file. The rows
   * the comparison found are shown, the equal ones only when asked: the
   * point is what differs. Only a new row can be added, ticked, and it is
   * written whole with what it owns; a row the table has is the
   * installation's, opened in its form to be changed by hand.
   */
  import { getContext } from 'svelte';
  import { _, _t } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';
  import { errorText } from '$kitebase/api/envelope';
  import DataView from '$kitebase/components/DataView.svelte';
  import DataFormView from '$kitebase/components/DataFormView.svelte';
  import { applyResult } from '$kitebase/components/resultAction';
  import { stack as globalStack, type StackInstance } from '$kitebase/stack/stack.svelte';
  import type { ViewDescriptor } from '$kitebase/components/dataview.types';

  interface Row {
    id: number | string;
    state: string;
    state_label: string;
    key: string;
    detail: string;
    db_id: unknown;
    form: string | null;
  }

  let { trigger }: {
    trigger?: { table?: string; set?: string; rows?: unknown[]; source?: string };
  } = $props();

  /** What the comparison is made with: the set, or the rows of the file. */
  const against = $derived(trigger?.set
    ? { table: trigger.table, set: trigger.set }
    : { table: trigger?.table, rows: trigger?.rows ?? [] });

  const stack = getContext<StackInstance>('kb:stack') ?? globalStack;

  let rows = $state<Row[]>([]);
  let error = $state<string | null>(null);
  let showEqual = $state(false);
  let ticked = $state<Row[]>([]);
  let busy = $state(false);

  const shown = $derived(showEqual ? rows : rows.filter(r => r.state !== 'equal'));
  const tickedNew = $derived(ticked.filter(r => r.state === 'new'));
  const counts = $derived.by(() => {
    const c: Record<string, number> = {};
    for (const r of rows) c[r.state] = (c[r.state] ?? 0) + 1;
    return c;
  });
  const COUNT_TEXT: Record<string, string> = {
    equal: '{n} equal', different: '{n} different', new: '{n} new',
    only_db: '{n} only in the table', ambiguous: '{n} ambiguous',
  };

  const view = {
    type: 'table',
    columns: [
      { field: 'state_label', title: _('State'), width: 140 },
      { field: 'key', title: _('Row'), width: 220 },
      { field: 'detail', title: _('What differs') },
    ],
    policy: { selection: true },
    navigator: { mode: 'readonly' },
  } as unknown as ViewDescriptor;

  async function load() {
    error = null;
    ticked = [];
    const res = await api.endpoint('seed_compare', against);
    if (res.status === 'success') rows = (res.data as Row[]) ?? [];
    else error = errorText(res, _('The operation failed'));
  }

  $effect(() => {
    if (trigger?.table && (trigger.set || trigger.rows)) void load();
  });

  async function addTicked() {
    busy = true;
    try {
      const res = await api.endpoint('seed_apply', { ...against, ids: tickedNew.map(r => r.id) });
      await applyResult(res, { title: _('Add the new rows ticked'), stack });
    } finally {
      busy = false;
      await load();
    }
  }

  function onEvent(name: string, data: unknown) {
    if (name === 'selection_change') {
      ticked = (data as Row[]) ?? [];
      return;
    }
    if (name !== 'row_dblclick' && name !== 'row_accept') return;
    const row = data as Row | null;
    if (!row?.form || row.db_id == null) return;
    stack.push(DataFormView, {
      formId: row.form, recordId: row.db_id, title: row.key,
      onSaved: () => void load(), onCancel: () => void load(),
    });
  }
</script>

<div class="seed-compare">
  <div class="head">
    <div class="what">
      <strong>{trigger?.table}</strong> &larr; {trigger?.set ?? trigger?.source}
      <span class="counts">
        {Object.entries(counts).map(([state, n]) => _t(COUNT_TEXT[state] ?? state, { n })).join(', ')}
      </span>
    </div>
    <label class="equal">
      <input type="checkbox" bind:checked={showEqual} />
      {_('Show equal rows')}
    </label>
    <button type="button" disabled={busy || tickedNew.length === 0} onclick={addTicked}>
      {_('Add the new rows ticked')}{tickedNew.length ? ` (${tickedNew.length})` : ''}
    </button>
  </div>
  <p class="note">
    {_('Tick the new rows to add them; open a row the table has to change it by hand.')}
    {#if ticked.length > tickedNew.length}
      <span class="warn">{_t('{n} ticked are not new: left alone', { n: ticked.length - tickedNew.length })}</span>
    {/if}
  </p>
  {#if error}
    <p class="error">{error}</p>
  {:else}
    <div class="grid">
      <DataView {view} data={shown} {onEvent} />
    </div>
  {/if}
</div>

<style>
  .seed-compare {
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--kb-border);
    color: var(--kb-text);
    font-size: 0.85rem;
  }
  .what { flex: 1; }
  .counts {
    margin-left: 0.75rem;
    color: var(--kb-text-subtle);
  }
  .equal {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    color: var(--kb-text-subtle);
  }
  button {
    border: 1px solid var(--kb-accent-border);
    border-radius: 0.25rem;
    background: var(--kb-accent);
    color: var(--kb-bg);
    padding: 0.3rem 0.7rem;
    font-size: 0.8rem;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .note {
    margin: 0;
    padding: 0.35rem 0.75rem;
    font-size: 0.8rem;
    color: var(--kb-text-subtle);
  }
  .warn {
    margin-left: 0.5rem;
    color: var(--kb-warning);
  }
  .error {
    padding: 1rem;
    color: var(--kb-danger);
  }
  .grid {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
</style>
