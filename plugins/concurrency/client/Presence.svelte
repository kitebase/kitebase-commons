<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    '{name} is editing this document, for {for}': '{name} sta modificando questo documento da {for}',
    '{name}: {doing}, for {for}': '{name}: {doing}, da {for}',
    'active now': 'attivo ora',
    'idle for {idle}': 'inattivo da {idle}',
    'less than a minute': 'meno di un minuto',
    '1 minute': '1 minuto',
    '{n} minutes': '{n} minuti',
    '1 hour': "1 ora",
    '{n} hours': '{n} ore',
    'Someone else saved this document meanwhile: when you save, your changes will be merged with theirs.':
      'Nel frattempo un altro ha salvato questo documento: al salvataggio le tue modifiche si fonderanno con le sue.',
  });
</script>

<script lang="ts">
  /**
   * Who else is editing the document of this form, mounted on top of every
   * form of a table (`form_areas.yaml`). Nothing when nobody is there.
   *
   * I show up at the first change, not when I open: whoever looks writes
   * nothing. My activity (a field changed, a frame opened or closed) renews
   * me, at most once every `every` seconds and only after something happened;
   * coming back to the window asks for the news. Every answer brings the
   * others and the version of the document: a version that is not the form's
   * means someone saved meanwhile, said now rather than at the save.
   */
  import { onDestroy, untrack } from 'svelte';
  import { _, _t } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';
  import { lifecycle, type FormRef } from '$kitebase/lifecycle';

  type Other = { user_name: string | null; doing: string | null; for: number; idle: number };
  type News = { version: string | null; others: Other[]; every: number };

  let { form, meta = {}, dirty = false }: {
    form: FormRef;
    meta?: Record<string, unknown>;
    dirty?: boolean;
  } = $props();

  // Who was there when the document opened: the news from then on are the calls'
  const opened = untrack(() => (meta.$presence ?? { others: [], every: 60 }) as
    { others: Other[]; every: number });
  let others = $state<Other[]>(opened.others ?? []);
  let every = opened.every || 60;
  let latest = $state<string | null>(null);
  /** When the seconds of `others` were measured, to age them while shown. */
  let measured = $state(Date.now());
  let now = $state(Date.now());

  let present = false;          // I hold a presence on the server
  let lastTouch = 0;
  let pending: ReturnType<typeof setTimeout> | null = null;

  const args = () => ({ model: form.model, id: form.id });

  async function ask(op: 'presence_touch' | 'presence_who' | 'presence_release') {
    if (form.id === null) return;
    try {
      const res = await api.endpoint<News>(op, args());
      if (res.status !== 'success' || !res.data) return;
      others = res.data.others;
      latest = res.data.version;
      every = res.data.every || every;
      measured = now = Date.now();
    } catch {
      // Advice only: a failed call leaves the banner as it was
    }
  }

  function touch() {
    if (pending) { clearTimeout(pending); pending = null; }
    present = true;
    lastTouch = Date.now();
    ask('presence_touch');
  }

  /** Something happened: renew now, or when the pace allows. */
  function active() {
    if (!present || pending) return;
    const wait = lastTouch + every * 1000 - Date.now();
    if (wait <= 0) touch();
    else pending = setTimeout(touch, wait);
  }

  const mine = (e: FormRef) => e.key === form.key;
  const onFocus = () => (present ? touch() : ask('presence_who'));
  const ticking = setInterval(() => (now = Date.now()), 30_000);

  const offs = [
    lifecycle.on('form:dirty', (e) => { if (mine(e) && e.dirty && !present) touch(); }),
    lifecycle.on('form:change', (e) => { if (mine(e)) active(); }),
    lifecycle.on('stack:push', active),
    lifecycle.on('stack:pop', active),
    lifecycle.on('form:saved', (e) => {
      if (mine(e) && present) { present = false; ask('presence_release'); }
    }),
  ];
  window.addEventListener('focus', onFocus);

  onDestroy(() => {
    offs.forEach((off) => off());
    window.removeEventListener('focus', onFocus);
    clearInterval(ticking);
    if (pending) clearTimeout(pending);
    // A courtesy: the presence expires anyway, whatever closes the form
    if (present) ask('presence_release');
  });

  function span(seconds: number): string {
    const minutes = Math.floor(seconds / 60);
    if (minutes < 1) return _('less than a minute');
    if (minutes < 60) return minutes === 1 ? _('1 minute') : _t('{n} minutes', { n: minutes });
    const hours = Math.floor(minutes / 60);
    return hours === 1 ? _('1 hour') : _t('{n} hours', { n: hours });
  }

  function line(o: Other, aged: number): string {
    const name = o.user_name ?? '?';
    const since = span(o.for + aged);
    if (o.doing) return _t('{name}: {doing}, for {for}', { name, doing: o.doing, for: since });
    const idle = o.idle + aged;
    const state = idle < 120 ? _('active now') : _t('idle for {idle}', { idle: span(idle) });
    return `${_t('{name} is editing this document, for {for}', { name, for: since })}, ${state}`;
  }

  let aged = $derived(Math.max(0, Math.round((now - measured) / 1000)));
  // The form's version moves with its saves and merges: only a newer one is news
  let saved = $derived(latest !== null && meta.$version !== undefined && latest !== meta.$version);
</script>

{#if others.length || (saved && dirty)}
  <div class="presence" role="status">
    {#each others as o, i (i)}
      <p>{line(o, aged)}</p>
    {/each}
    {#if saved && dirty}
      <p class="saved">{_('Someone else saved this document meanwhile: when you save, your changes will be merged with theirs.')}</p>
    {/if}
  </div>
{/if}

<style>
  .presence {
    padding: 0.35rem 0.75rem;
    font-size: 0.8rem;
    color: var(--kb-text);
    background: color-mix(in srgb, var(--kb-warning, #f59e0b) 10%, var(--kb-surface));
    border-bottom: 1px solid color-mix(in srgb, var(--kb-warning, #f59e0b) 35%, transparent);
  }
  .presence p {
    margin: 0;
  }
  .saved {
    font-weight: 600;
  }
</style>
