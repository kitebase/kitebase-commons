<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Loading...': 'Caricamento...',
    'Nothing to do': 'Niente da fare',
    'No activities yet': 'Nessuna attività',
    'Save the record to write its activities': 'Salva il record per scriverne le attività',
    'What is it about?': 'Di cosa si tratta?',
    'Add': 'Aggiungi',
    'Type': 'Tipo',
    'Due': 'Scadenza',
    'Overdue': 'Scaduta',
    'Today': 'Oggi',
    'No date': 'Senza data',
    'Done': 'Fatta',
    'Mark done': 'Segna fatta',
    'To do again': 'Di nuovo da fare',
    'Tomorrow': 'Domani',
    'In a week': 'Fra una settimana',
    'Postpone': 'Rimanda',
    'on': 'su',
    'from': 'da',
    'Priority': 'Priorità',
    'Error': 'Errore',
    'To do': 'Da fare',
    'All': 'Tutte',
    'Show': 'Mostra',
    'Open': 'Apri',
    'Delete': 'Elimina',
    'Delete this activity?': 'Eliminare questa attività?',
    'Activity': 'Attività',
  });
</script>

<script lang="ts">
  /**
   * The list of activities shown by `activities.timeline` (one record),
   * `activities.mine` (the user's own) and `activities.agenda` (a user's),
   * with the line that writes a new one and the filter on what is to do.
   *
   * To do first, done after, as the server sorts them. A thing to do is
   * marked done or postponed in place; a done one with a date can be made to
   * do again. A new activity with no due date is a fact recorded, done now.
   * The subject opens the activity's form (`activity_form`) on the stack, for
   * what the line does not write; the list reads again when it is closed.
   */
  import { getContext } from 'svelte';
  import { stack as globalStack } from '$kitebase/stack/stack.svelte';
  import type { StackInstance } from '$kitebase/stack/stack.svelte';
  import DataFormView from '$kitebase/components/DataFormView.svelte';
  import { msgbox } from '$kitebase/components/msgbox.svelte';
  import { _ } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';
  import { errorText } from '$kitebase/api/envelope';
  import { resolveIcon } from '$kitebase/components/icons';
  import { ToggleGroup } from 'bits-ui';
  import { Circle, CircleCheck, List, Trash2 } from '@lucide/svelte';

  interface Ref {
    model: string;
    id: string;
    label: string | null;
  }

  interface Item {
    id: number;
    type: string;
    type_label: string;
    icon: string | null;
    subject: string;
    note: string | null;
    user_id: number | null;
    user: string | null;
    author_id: number | null;
    author: string | null;
    start_at: string | null;
    due_date: string | null;
    done_at: string | null;
    day: string | null;
    when: 'overdue' | 'today' | 'upcoming' | 'open' | 'done';
    priority: number;
    owner: Ref | null;
  }

  interface TypeOption {
    value: string;
    label: string;
    icon: string | null;
  }

  interface Props {
    /** The endpoint that lists: activity_timeline or activity_mine. */
    endpoint: string;
    /** The record of a timeline, sent with the list and with a new activity. */
    record?: { model: string; id: string | number } | null;
    /** The user of an agenda: whose list it is, and who a new one is for. */
    userId?: string | number | null;
    /** What is shown first: what is to do, what is done, or all. */
    defaultState?: State;
    /** The text of an empty list. */
    empty: string;
    /** The type a new activity starts from; the first one offered if missing. */
    defaultType?: string;
    /** Say who each activity is assigned to: not in the user's own list. */
    showUser?: boolean;
    /** Called after every change, with the activities still to do. */
    onchange?: (todo: number) => void;
    /** Read again whenever it changes: the trigger of a split area, which a
     *  list sends anew when the row under the cursor may have changed. */
    refresh?: unknown;
  }

  type State = 'todo' | 'done' | 'all';

  let {
    endpoint, record = null, userId = null, empty, defaultType, defaultState = 'all',
    showUser = true, onchange, refresh,
  }: Props = $props();

  const stack = getContext<StackInstance>('kb:stack') ?? globalStack;

  const STATES = [
    { value: 'todo', text: 'To do', Icon: Circle },
    { value: 'done', text: 'Done', Icon: CircleCheck },
    { value: 'all', text: 'All', Icon: List },
  ] as const;
  // svelte-ignore state_referenced_locally
  let show = $state<State>(defaultState);

  let items = $state<Item[]>([]);
  let types = $state<TypeOption[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let type = $state('');
  let subject = $state('');
  let due = $state('');
  let saving = $state(false);
  let postponing = $state<number | null>(null);

  /** What names the list, and the record or user a new activity goes to. */
  const target = $derived({
    ...(record ? { model: record.model, id: record.id } : {}),
    ...(userId !== null && userId !== undefined ? { user_id: userId } : {}),
  });
  const params = $derived({ ...target, state: show });

  async function load() {
    const res = await api.endpoint(endpoint, params);
    loading = false;
    if (res.status === 'success') {
      items = res.data as Item[];
      error = null;
      if (show !== 'done') onchange?.(items.filter((i) => i.when !== 'done').length);
    } else {
      error = errorText(res, _('Error'));
    }
  }

  async function loadTypes() {
    const res = await api.endpoint('activity_types', {});
    if (res.status === 'success') {
      types = res.data as TypeOption[];
      if (!type && types.length) {
        type = types.some((t) => t.value === defaultType) ? defaultType! : types[0].value;
      }
    }
  }

  $effect(() => {
    void params;
    void refresh;
    loading = true;
    void load();
  });

  $effect(() => {
    void loadTypes();
  });

  async function act(op: string, data: Record<string, unknown>) {
    const res = await api.endpoint(op, data);
    if (res.status !== 'success') {
      error = errorText(res, _('Error'));
      return false;
    }
    error = null;
    await load();
    return true;
  }

  async function add(event: SubmitEvent) {
    event.preventDefault();
    if (!subject.trim() || !type || saving) return;
    saving = true;
    const ok = await act('activity_add', {
      ...target, type, subject: subject.trim(), due_date: due || null,
    });
    saving = false;
    if (ok) {
      subject = '';
      due = '';
    }
  }

  /** The day `days` from today, as YYYY-MM-DD in local time. */
  function shift(days: number): string {
    const d = new Date();
    d.setDate(d.getDate() + days);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  /** The whole activity, in its form: the list reads again when it closes. */
  function open(item: Item) {
    stack.push(DataFormView, {
      formId: 'activity_form', recordId: item.id, title: _('Activity'),
      onSaved: () => void load(), onCancel: () => void load(),
    });
  }

  async function remove(item: Item) {
    if (!(await msgbox.confirm(_('Delete this activity?'), item.subject))) return;
    await act('db', { table: 'Activity', method: 'delete', id: item.id });
  }

  async function postpone(id: number, date: string) {
    postponing = null;
    if (date) await act('activity_postpone', { id, date });
  }

  function whenText(item: Item): string {
    if (item.when === 'done') return item.done_at ? item.done_at.slice(0, 10) : _('Done');
    if (item.when === 'overdue') return `${_('Overdue')} ${item.day}`;
    if (item.when === 'today') return item.start_at ? item.start_at.slice(11) : _('Today');
    if (item.when === 'open') return _('No date');
    return item.start_at ?? item.day ?? '';
  }
</script>

<div class="activities">
  <form class="add" onsubmit={add}>
    <select bind:value={type} aria-label={_('Type')}>
      {#each types as t (t.value)}
        <option value={t.value}>{t.label}</option>
      {/each}
    </select>
    <input class="subject" bind:value={subject} placeholder={_('What is it about?')} />
    <input type="date" bind:value={due} title={_('Due')} aria-label={_('Due')} />
    <button type="submit" disabled={!subject.trim() || saving}>{_('Add')}</button>
    <!-- What the list shows: one of three, never none -->
    <ToggleGroup.Root type="single" class="filter" aria-label={_('Show')} value={show}
                      onValueChange={(v) => { if (v) show = v as State; }}>
      {#each STATES as { value, text, Icon } (value)}
        <ToggleGroup.Item {value} class="filter-item" title={_(text)} aria-label={_(text)}>
          <Icon size={14} />
        </ToggleGroup.Item>
      {/each}
    </ToggleGroup.Root>
  </form>

  {#if error}
    <p class="note error">{error}</p>
  {/if}

  {#if loading}
    <p class="note">{_('Loading...')}</p>
  {:else if !items.length}
    <p class="note">{empty}</p>
  {:else}
    <ul>
      {#each items as item (item.id)}
        {@const Icon = resolveIcon(item.icon ?? undefined)}
        <li class="item {item.when}">
          <span class="icon" title={item.type_label}>
            {#if Icon}<Icon size={16} />{:else}{item.type_label.slice(0, 1)}{/if}
          </span>
          <div class="body">
            <div class="line">
              <button type="button" class="subject" title={_('Open')}
                      onclick={() => open(item)}>{item.subject}</button>
              {#if item.priority}
                <span class="priority" class:high={item.priority > 0}
                      title={_('Priority')}>{item.priority > 0 ? '+' : ''}{item.priority}</span>
              {/if}
            </div>
            <div class="meta">
              <span class="when">{whenText(item)}</span>
              {#if showUser && item.user}<span>{item.user}</span>{/if}
              {#if item.author && item.author_id !== item.user_id}
                <span>{_('from')} {item.author}</span>
              {/if}
              {#if item.owner}
                <span>{_('on')} {item.owner.label ?? `${item.owner.model} ${item.owner.id}`}</span>
              {/if}
            </div>
            {#if item.note}<p class="text">{item.note}</p>{/if}
          </div>
          <div class="actions">
            {#if item.when === 'done'}
              {#if item.day}
                <button type="button" onclick={() => act('activity_done', { id: item.id, done: false })}>
                  {_('To do again')}
                </button>
              {/if}
            {:else}
              {#if postponing === item.id}
                <button type="button" onclick={() => postpone(item.id, shift(1))}>{_('Tomorrow')}</button>
                <button type="button" onclick={() => postpone(item.id, shift(7))}>{_('In a week')}</button>
                <input type="date" aria-label={_('Postpone')}
                       onchange={(e) => postpone(item.id, (e.currentTarget as HTMLInputElement).value)} />
              {:else}
                <button type="button" onclick={() => (postponing = item.id)}>{_('Postpone')}</button>
              {/if}
              <button type="button" class="done" onclick={() => act('activity_done', { id: item.id })}>
                {_('Mark done')}
              </button>
            {/if}
            <button type="button" class="remove" title={_('Delete')} aria-label={_('Delete')}
                    onclick={() => remove(item)}><Trash2 size={14} /></button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .activities {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    color: var(--kb-text);
    font-size: 0.875rem;
  }
  .add {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }
  .add .subject {
    flex: 1 1 12rem;
  }
  input,
  select {
    border: 1px solid var(--kb-border-input);
    border-radius: 0.25rem;
    background: var(--kb-surface);
    color: var(--kb-text);
    padding: 0.25rem 0.5rem;
  }
  button {
    border: 1px solid var(--kb-border);
    border-radius: 0.25rem;
    background: var(--kb-surface);
    color: var(--kb-text);
    padding: 0.25rem 0.5rem;
    font-size: 0.8rem;
    cursor: pointer;
  }
  button:hover:not(:disabled) {
    background: var(--kb-surface-hover);
  }
  button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .add button[type='submit'],
  button.done {
    border-color: var(--kb-accent-border);
    color: var(--kb-accent);
  }
  .add :global(.filter) {
    display: inline-flex;
    margin-left: auto;
    border: 1px solid var(--kb-border);
    border-radius: 0.25rem;
    overflow: hidden;
  }
  .add :global(.filter-item) {
    border: none;
    border-radius: 0;
    background: var(--kb-surface);
    color: var(--kb-text-subtle);
    padding: 0.25rem 0.4rem;
    display: flex;
    align-items: center;
    cursor: pointer;
  }
  .add :global(.filter-item + .filter-item) {
    border-left: 1px solid var(--kb-border);
  }
  .add :global(.filter-item[data-state='on']) {
    background: var(--kb-surface-hover);
    color: var(--kb-accent);
    font-weight: 600;
  }
  .note {
    color: var(--kb-text-subtle);
    margin: 0.5rem 0;
  }
  .note.error {
    color: var(--kb-danger);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .item {
    display: flex;
    gap: 0.625rem;
    align-items: flex-start;
    padding: 0.5rem 0;
    border-top: 1px solid var(--kb-border);
  }
  .item.done {
    color: var(--kb-text-muted);
  }
  .icon {
    flex: 0 0 1.5rem;
    display: flex;
    justify-content: center;
    padding-top: 0.125rem;
    color: var(--kb-text-subtle);
  }
  .body {
    flex: 1 1 auto;
    min-width: 0;
  }
  .line {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
  }
  button.remove {
    border-color: transparent;
    color: var(--kb-text-subtle);
    display: flex;
    align-items: center;
  }
  button.remove:hover {
    color: var(--kb-danger);
  }
  button.subject {
    border: none;
    background: none;
    padding: 0;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  button.subject:hover {
    color: var(--kb-accent);
    text-decoration: underline;
    background: none;
  }
  .item:not(.done) .subject {
    font-weight: 500;
  }
  .priority {
    font-size: 0.7rem;
    color: var(--kb-text-subtle);
  }
  .priority.high {
    color: var(--kb-warning);
    font-weight: 600;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    font-size: 0.75rem;
    color: var(--kb-text-subtle);
  }
  .overdue .when {
    color: var(--kb-danger);
    font-weight: 600;
  }
  .today .when {
    color: var(--kb-accent);
    font-weight: 600;
  }
  .text {
    margin: 0.25rem 0 0;
    white-space: pre-wrap;
  }
  .actions {
    flex: 0 0 auto;
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    justify-content: flex-end;
  }
  /* A narrow pane, beside a form: the buttons go under the text */
  @container (max-width: 30rem) {
    .item {
      flex-wrap: wrap;
    }
    .actions {
      flex-basis: 100%;
      justify-content: flex-start;
      padding-left: 2.125rem;
    }
  }
</style>
