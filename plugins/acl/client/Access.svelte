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
  });
</script>

<script lang="ts">
  /**
   * What a user may do, table by table: the roles of the form's draft resolved
   * into permissions by the server (acl_effective), so ticking a role shows
   * what it brings before anything is saved.
   * Registry ID: acl.access, used as a form widget (`widget: acl.access`).
   *
   * Each cell is given, taken away inside a role (`-T.label`), or neither; the
   * tooltip names the roles. Below the tables, the other permissions: those of
   * pages, menus, endpoints and reports. Read only: it shows the roles, it
   * does not change them.
   */
  import { _ } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';

  interface Answer {
    ok: boolean;
    by: string[];
    denied_by: string[];
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
    actions: string[];
    tables: TableRow[];
    permissions: PermissionRow[];
  }

  interface Props {
    value: unknown;
    record?: Record<string, unknown>;
    [key: string]: unknown;
  }

  let { value, record = {} }: Props = $props();

  let data = $state<Effective | null>(null);
  let error = $state<string | null>(null);
  let onlyGiven = $state(true);

  const roles = $derived(Array.isArray(value) ? (value as string[]) : []);
  const isAdmin = $derived(Boolean(record.is_admin));
  // One request per distinct question, and the last one asked wins.
  const question = $derived(JSON.stringify({ roles, is_admin: isAdmin }));

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

  const given = (row: TableRow) => Object.values(row.actions).some((a) => a.ok || a.denied_by.length);

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
    (data?.permissions ?? []).filter((p) => !onlyGiven || p.ok || p.denied_by.length),
  );

  function tip(a: Answer): string {
    const parts = [];
    if (a.by.length) parts.push(`${_('given by')} ${a.by.join(', ')}`);
    if (a.denied_by.length) parts.push(`${_('taken away in')} ${a.denied_by.join(', ')}`);
    return parts.join('; ');
  }

  function markOf(a: Answer): string {
    return a.ok ? 'given' : a.denied_by.length ? 'denied' : 'none';
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
                  <td class="cell" title={tip(a)}><span class="mark {markOf(a)}"></span></td>
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
              <td class="cell" title={tip(p)}><span class="mark {markOf(p)}"></span></td>
            </tr>
          {/each}
        </tbody>
      </table>
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
    display: inline-block;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 50%;
    border: 1px solid var(--kb-border-input);
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
