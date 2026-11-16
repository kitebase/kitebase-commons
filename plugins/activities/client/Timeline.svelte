<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'Pick a row to see its activities': 'Scegli una riga per vederne le attività',
  });
</script>

<script lang="ts">
  /**
   * The activities of one record. Registry ID: activities.timeline. In a
   * split area beside a list, the view names the table in `props.model` and
   * the area's trigger gives the row (`trigger: {event: row_click, pass:
   * [id]}`); beside a form, `form_load` does the same. In a form's layout
   * (`{type: plugin, component: activities.timeline}`) the form gives both,
   * and a new record has none yet.
   */
  import { _ } from '$kitebase/i18n';
  import Activities, { type RowCommand } from './Activities.svelte';

  interface Props {
    model?: string;
    recordId?: string | number | null;
    trigger?: Record<string, unknown>;
    /** Commands on the rows, declared by the page (`props.commands`). */
    commands?: RowCommand[];
    /** The page's: told `changed` when the history wrote something. */
    onEvent?: (name: string, data: unknown) => void;
  }

  let { model, recordId, trigger, commands = [], onEvent }: Props = $props();

  const id = $derived(recordId ?? (trigger?.id as string | number | null | undefined));
</script>

<div class="timeline">
  {#if model && id !== null && id !== undefined && id !== ''}
    <Activities endpoint="activity_timeline" record={{ model, id }} refresh={trigger}
                {commands} {onEvent} empty={_('No activities yet')} />
  {:else if recordId === undefined}
    <p class="note">{_('Pick a row to see its activities')}</p>
  {:else}
    <p class="note">{_('Save the record to write its activities')}</p>
  {/if}
</div>

<style>
  .timeline {
    height: 100%;
    overflow-y: auto;
    padding: 0.5rem 0.75rem;
  }
  .note {
    color: var(--kb-text-subtle);
    font-size: 0.875rem;
  }
</style>
