<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Cancel': 'Annulla',
    'Cancelling...': 'Annullamento in attesa...',
    'Stop this work': 'Ferma questo lavoro',
  });
</script>

<script lang="ts">
  /**
   * The works in progress of the person, beside the status line of the chrome
   * (`chrome_areas.yaml`). Nothing when nothing is open.
   *
   * The server says when to look again: soon while a work is open, slowly
   * otherwise (`next` of `jobs_poll`). The client looks sooner when one of its
   * calls is still waiting after a second, since that is a work that may be
   * saying something; and never while the tab is hidden, once at once when it
   * comes back.
   */
  import { onDestroy, onMount } from 'svelte';
  import { _ } from '$kitebase/i18n';
  import { api } from '$kitebase/api/client';
  import { activity } from '$kitebase/api/activity.svelte';

  type Work = {
    key: string; doing: string | null; done: number | null; total: number | null;
    cancellable: boolean; cancel_requested: boolean; for: number;
  };

  let works = $state<Work[]>([]);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let peek: ReturnType<typeof setTimeout> | null = null;
  let polling = false;
  let stopped = false;

  function schedule(seconds: number) {
    if (timer) clearTimeout(timer);
    timer = null;
    if (stopped || document.hidden) return;
    timer = setTimeout(poll, Math.max(0.5, seconds) * 1000);
  }

  async function poll() {
    if (polling || stopped) return;
    polling = true;
    let next = 30;
    try {
      const res = await api.endpoint<{ works: Work[]; next: number }>('jobs_poll', {},
                                                                       { background: true });
      if (res.status === 'success' && res.data) {
        works = res.data.works ?? [];
        next = res.data.next ?? next;
      }
    } finally {
      polling = false;
      schedule(next);
    }
  }

  // A call of mine still waiting after a second: look now, it may be a work
  $effect(() => {
    if (activity.pending > 0) {
      if (!peek) peek = setTimeout(() => {
        peek = null;
        if (activity.pending > 0 && works.length === 0) poll();
      }, 1000);
    } else if (peek) {
      clearTimeout(peek);
      peek = null;
    }
  });

  function onVisibility() {
    if (document.hidden) schedule(0);   // clears the timer: nothing while hidden
    else poll();
  }

  async function cancel(work: Work) {
    work.cancel_requested = true;
    await api.endpoint('jobs_cancel', { key: work.key }, { background: true });
    poll();
  }

  function counter(work: Work): string {
    if (work.total) return `${work.done ?? 0}/${work.total}`;
    return work.done != null ? String(work.done) : '';
  }

  onMount(() => {
    document.addEventListener('visibilitychange', onVisibility);
    poll();
  });

  onDestroy(() => {
    stopped = true;
    document.removeEventListener('visibilitychange', onVisibility);
    if (timer) clearTimeout(timer);
    if (peek) clearTimeout(peek);
  });
</script>

{#each works as work (work.key)}
  <div class="kb-work" role="status">
    <span class="kb-work-spin" aria-hidden="true"></span>
    <span class="kb-work-text">{work.doing ?? ''}</span>
    {#if counter(work)}<span class="kb-work-count">{counter(work)}</span>{/if}
    {#if work.cancel_requested}
      <span class="kb-work-note">{_('Cancelling...')}</span>
    {:else if work.cancellable}
      <button class="kb-work-cancel" title={_('Stop this work')} onclick={() => cancel(work)}>
        {_('Cancel')}
      </button>
    {/if}
  </div>
{/each}

<style>
  .kb-work {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
    font-size: 0.78rem;
    color: var(--kb-text);
  }
  .kb-work-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .kb-work-count {
    flex: 0 0 auto;
    color: var(--kb-text-muted);
    font-variant-numeric: tabular-nums;
  }
  .kb-work-note {
    flex: 0 0 auto;
    color: var(--kb-text-muted);
    font-style: italic;
  }
  .kb-work-spin {
    flex: 0 0 auto;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 9999px;
    border: 2px solid var(--kb-border);
    border-top-color: var(--kb-accent);
    animation: kb-work-spin 0.8s linear infinite;
  }
  .kb-work-cancel {
    flex: 0 0 auto;
    padding: 0 0.4rem;
    font-size: 0.75rem;
    border: 1px solid var(--kb-border);
    border-radius: 0.25rem;
    background: var(--kb-surface);
    color: var(--kb-text);
    cursor: pointer;
  }
  .kb-work-cancel:hover {
    background: var(--kb-surface-hover);
  }
  @keyframes kb-work-spin {
    to { transform: rotate(360deg); }
  }
</style>
