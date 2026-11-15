<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Pick a user to see what they have to do': 'Scegli un utente per vedere cosa ha da fare',
  });
</script>

<script lang="ts">
  /**
   * The activities assigned to one user, for whoever reads every activity.
   * Registry ID: activities.agenda, in a split area beside the list of users:
   * the area's trigger gives the user (`trigger: {event: row_click, pass:
   * [id]}`), or `userId` names them. What is written here is for that user.
   */
  import { _ } from '$kitebase/i18n';
  import Activities from './Activities.svelte';

  interface Props {
    userId?: string | number | null;
    trigger?: Record<string, unknown>;
  }

  let { userId, trigger }: Props = $props();

  const id = $derived(userId ?? (trigger?.id as string | number | null | undefined));
</script>

<div class="agenda">
  {#if id !== null && id !== undefined && id !== ''}
    {#key id}
      <Activities endpoint="activity_mine" userId={id} refresh={trigger} empty={_('Nothing to do')}
                  defaultType="todo" defaultState="todo" showUser={false} />
    {/key}
  {:else}
    <p class="note">{_('Pick a user to see what they have to do')}</p>
  {/if}
</div>

<style>
  .agenda {
    height: 100%;
    overflow-y: auto;
    padding: 0.5rem 0.75rem;
  }
  .note {
    color: var(--kb-text-subtle);
    font-size: 0.875rem;
  }
</style>
