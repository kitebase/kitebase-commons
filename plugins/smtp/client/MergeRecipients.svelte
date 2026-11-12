<script lang="ts">
  /**
   * The summary of a mail merge: how many messages, to how many addresses,
   * who goes to the fallback, who is skipped. Registry ID:
   * smtp.mergerecipients, the widget of the merge form's `recipients`.
   *
   * It shows what the server wrote in the draft, and asks again
   * (smtp_merge_recipients) whenever the form changes whom inside each
   * record: `functions`, `fallback`, `per_contact`. Read only: the value is
   * the server's.
   */
  import { untrack } from 'svelte';
  import { api } from '$kitebase/api/client';
  import { errorText } from '$kitebase/api/envelope';
  import { _ } from '$kitebase/i18n';

  interface Props {
    value: unknown;
    record?: Record<string, unknown>;
  }

  let { value, record }: Props = $props();

  let text = $state(untrack(() => (typeof value === 'string' ? value : '')));
  let failed = $state(false);

  // What the summary depends on, as one key: a change of anything else in
  // the form (the text, the subject) asks nothing
  const key = $derived(JSON.stringify({
    model: record?.model, ids: record?.ids, functions: record?.functions ?? [],
    fallback: record?.fallback ?? 'main', per_contact: !!record?.per_contact,
  }));

  let asked = untrack(() => key);
  let timer: ReturnType<typeof setTimeout> | undefined;

  $effect(() => {
    const current = key;
    if (current === asked) return;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      asked = current;
      const res = await api.endpoint<string>('smtp_merge_recipients', { data: JSON.parse(current) });
      if (current !== asked) return;
      failed = res.status !== 'success';
      text = failed ? errorText(res, _('Error')) : (res.data ?? '');
    }, 250);
    return () => clearTimeout(timer);
  });
</script>

<span class="kb-merge-recipients" class:failed>{text}</span>

<style>
  .kb-merge-recipients {
    display: block;
    padding: 0.4rem 0;
    font-size: 0.875rem;
    color: var(--kb-text);
    min-height: 2rem;
    line-height: 1.5;
  }
  .failed { color: var(--kb-danger); }
</style>
