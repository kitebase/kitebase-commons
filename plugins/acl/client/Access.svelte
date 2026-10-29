<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  // A plugin component brings its own strings: the library's catalogue is the
  // library's, and the YAML labels are translated by the server.
  registerTranslations('it', {
    'Only what is given': 'Solo ciò che è concesso',
    'given by': 'concesso da',
    'taken away in': 'tolto in',
    'Other permissions': 'Altri permessi',
    'Loading...': 'Caricamento...',
    'An administrator passes every check, whatever the roles.':
      'Un amministratore passa ogni controllo, qualunque siano i ruoli.',
    'Unknown roles, which give nothing:': 'Ruoli sconosciuti, che non danno nulla:',
    'No table: these roles give nothing on the data.':
      'Nessuna tabella: questi ruoli non danno nulla sui dati.',
    'The access could not be computed': "Non è stato possibile calcolare l'accesso",
    'granted to this user': 'concesso a questo utente',
    'denied to this user': 'negato a questo utente',
    'click: inherit, grant, deny': 'clic: eredita, concedi, nega',
    'Pages this user opens but cannot read:': 'Pagine che questo utente apre ma non può leggere:',
    'reads': 'legge',
    'it needs': 'serve',
  });
</script>

<script lang="ts">
  /**
   * What a user may do, table by table: the roles and exceptions of the
   * form's draft resolved into permissions by the server (acl_effective), so a
   * ticked role or a forced cell shows what it gives before anything is saved.
   * Registry ID: acl.access, the widget of the user's exceptions
   * (`widget: acl.access` on `acl_exceptions`); the roles are read from the
   * draft, from the field named by `roles_field` (default `roles`).
   *
   * Each cell is given, taken away inside a role (`-T.label`), or neither; the
   * tooltip names the roles. A click cycles the user's own exception on it:
   * inherit, grant (+), deny (-). Below, the other permissions (pages, menus,
   * endpoints, reports), and the pages these permissions open but cannot read:
   * at the end, so that growing they do not move the cells under the mouse.
   */
  import { _ } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';

  interface Answer {
    ok: boolean;
    by: string[];
    denied_by: string[];
    forced: '+' | '-' | null;
  }

  interface Problem {
    page: string;
    title: string | null;
    what: string;
    grant: string;
  }

  interface TableRow {
    name: string;
    label: string;
    plugin: string;
    actions: Record<string, Answer>;
  }

  interface PermissionRow extends Answer {
    code: string;
    label: string;
  }

  interface Effective {
    admin: boolean;
    unknown: string[];
    problems: Problem[];
    actions: string[];
    tables: TableRow[];
    permissions: PermissionRow[];
  }

  interface Props {
    value: unknown;
    onchange?: (v: string[]) => void;
    readonly?: boolean;
    record?: Record<string, unknown>;
    field?: Record<string, unknown>;
    [key: string]: unknown;
  }

  let { value, onchange, readonly = false, record = {}, field = {} }: Props = $props();

  let data = $state<Effective | null>(null);
  let error = $state<string | null>(null);
  let onlyGiven = $state(true);

  const codes = (v: unknown) =>
    Array.isArray(v) ? (v as unknown[]).filter((c): c is string => typeof c === 'string') : [];

  const exceptions = $derived(codes(value));
  const roles = $derived(codes(record[(field.roles_field as string) ?? 'roles']));
  const isAdmin = $derived(Boolean(record.is_admin));
  // One request per distinct question, and the last one asked wins.
  const question = $derived(JSON.stringify({ roles, exceptions, is_admin: isAdmin }));

  let asked = 0;
  $effect(() => {
    const body = JSON.parse(question);
    const ticket = ++asked;
    const timer = setTimeout(async () => {
      try {
        const res = await api.endpoint('acl_effective', body);
        if (ticket !== asked) return;
        if (res.status === 'success') {
          data = res.data as Effective;
          error = null;
        } else {
          error = res.message ?? _('The access could not be computed');
        }
      } catch (e) {
        if (ticket === asked) error = e instanceof Error ? e.message : String(e);
      }
    }, 250);
    return () => clearTimeout(timer);
  });

  const shown = (a: Answer) => a.ok || a.denied_by.length > 0 || a.forced !== null;
  const given = (row: TableRow) => Object.values(row.actions).some(shown);

  const groups = $derived.by(() => {
    const out: Array<[string, TableRow[]]> = [];
    for (const row of data?.tables ?? []) {
      if (onlyGiven && !given(row)) continue;
      const last = out[out.length - 1];
      if (last && last[0] === row.plugin) last[1].push(row);
      else out.push([row.plugin, [row]]);
    }
    return out;
  });

  const permissions = $derived(
    (data?.permissions ?? []).filter((p) => !onlyGiven || shown(p)),
  );

  function tip(a: Answer): string {
    const parts = [];
    if (a.by.length) parts.push(`${_('given by')} ${a.by.join(', ')}`);
    if (a.denied_by.length) parts.push(`${_('taken away in')} ${a.denied_by.join(', ')}`);
    if (a.forced === '+') parts.push(_('granted to this user'));
    if (a.forced === '-') parts.push(_('denied to this user'));
    if (!readonly && !data?.admin) parts.push(_('click: inherit, grant, deny'));
    return parts.join('; ');
  }

  /** This user's own exception on exactly this permission: what a click cycles. */
  function own(code: string): '+' | '-' | null {
    if (exceptions.includes(`-${code}`)) return '-';
    if (exceptions.includes(`+${code}`)) return '+';
    return null;
  }

  function cycle(code: string) {
    if (readonly || data?.admin || !onchange) return;
    const current = own(code);
    const next = current === null ? '+' : current === '+' ? '-' : null;
    const rest = exceptions.filter((e) => e !== `+${code}` && e !== `-${code}`);
    onchange(next ? [...rest, `${next}${code}`] : rest);
  }

  function markOf(a: Answer): string {
    return a.ok ? 'given' : a.forced === '-' || a.denied_by.length ? 'denied' : 'none';
  }
</script>

<div class="access">
  <label class="toggle">
    <input type="checkbox" bind:checked={onlyGiven} />
    {_('Only what is given')}
  </label>

  {#if error}
    <p class="note">{error}</p>
  {:else if !data}
    <p class="note">{_('Loading...')}</p>
  {:else}
    {#if data.admin}
      <p class="note">{_('An administrator passes every check, whatever the roles.')}</p>
    {/if}
    {#if data.unknown.length}
      <p class="note">{_('Unknown roles, which give nothing:')} {data.unknown.join(', ')}</p>
    {/if}

    {#if groups.length}
      <table>
        <thead>
          <tr>
            <th></th>
            {#each data.actions as action (action)}<th class="cell">{action}</th>{/each}
          </tr>
        </thead>
        {#each groups as [plugin, rows] (plugin)}
          <tbody>
            <tr><th class="group" colspan={data.actions.length + 1}>{plugin}</th></tr>
            {#each rows as row (row.name)}
              <tr>
                <td>{row.label}</td>
                {#each data.actions as action (action)}
                  {@const a = row.actions[action]}
                  {@const code = `${row.name}.${action}`}
                  <td class="cell" title={tip(a)}>
                    <button type="button" class="mark {markOf(a)}" class:forced={a.forced}
                      disabled={readonly || data.admin} onclick={() => cycle(code)}
                      aria-label="{row.label} {action}">{own(code) ?? ''}</button>
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        {/each}
      </table>
    {:else}
      <p class="note">{_('No table: these roles give nothing on the data.')}</p>
    {/if}

    {#if permissions.length}
      <table class="permissions">
        <thead><tr><th>{_('Other permissions')}</th><th class="cell"></th></tr></thead>
        <tbody>
          {#each permissions as p (p.code)}
            <tr>
              <td>{p.label}{#if p.label !== p.code} <code>{p.code}</code>{/if}</td>
              <td class="cell" title={tip(p)}>
                <button type="button" class="mark {markOf(p)}" class:forced={p.forced}
                  disabled={readonly || data.admin} onclick={() => cycle(p.code)}
                  aria-label={p.label}>{own(p.code) ?? ''}</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    {#if data.problems.length}
      <div class="problems">
        <p>{_('Pages this user opens but cannot read:')}</p>
        <ul>
          {#each data.problems as pr (pr.page + pr.what)}
            <li>
              <strong>{pr.title ?? pr.page}</strong>: {_('reads')} <code>{pr.what}</code>;
              {_('it needs')} <code>{pr.grant}</code>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}
</div>

<style>
  .access {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    font-size: 0.875rem;
    color: var(--kb-text);
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    color: var(--kb-text-subtle);
  }
  input {
    accent-color: var(--kb-accent);
  }
  table {
    border-collapse: collapse;
    width: 100%;
    max-width: 40rem;
  }
  th,
  td {
    padding: 0.25rem 0.5rem;
    border-bottom: 1px solid var(--kb-border);
    text-align: left;
  }
  th {
    font-weight: 600;
    color: var(--kb-text-subtle);
  }
  th.group {
    padding-top: 0.6rem;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .cell {
    width: 4.5rem;
    text-align: center;
  }
  .mark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1rem;
    height: 1rem;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--kb-border-input);
    background: transparent;
    font-size: 0.7rem;
    font-weight: 700;
    line-height: 1;
    color: var(--kb-bg);
    cursor: pointer;
  }
  .mark:disabled {
    cursor: default;
  }
  .mark.none {
    color: var(--kb-text);
  }
  /* The user's own exception: a ring around the mark. */
  .mark.forced {
    box-shadow: 0 0 0 2px var(--kb-bg), 0 0 0 3.5px var(--kb-text-subtle);
  }
  .problems {
    max-width: 40rem;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--kb-danger);
    border-radius: 0.375rem;
    color: var(--kb-text);
  }
  .problems p,
  .problems ul {
    margin: 0;
  }
  .problems ul {
    padding-left: 1.25rem;
  }
  .mark.given {
    background: var(--kb-accent);
    border-color: var(--kb-accent);
  }
  .mark.denied {
    background: var(--kb-danger);
    border-color: var(--kb-danger);
  }
  code {
    font-size: 0.8em;
    color: var(--kb-text-subtle);
  }
  .note {
    margin: 0;
    color: var(--kb-text-subtle);
  }
</style>
