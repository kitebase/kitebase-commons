<script module lang="ts">
  import { registerTranslations } from '$kitebase/i18n';

  registerTranslations('it', {
    'My activities': 'Le mie attività',
  });
</script>

<script lang="ts">
  /**
   * What the user has to do. Registry ID: activities.mine, a page of
   * `type: plugin`. What is written here is personal, on no record.
   */
  import { _ } from '$kitebase/i18n';
  import Activities from './Activities.svelte';
</script>

<div class="mine">
  <h2>{_('My activities')}</h2>
  <Activities endpoint="activity_mine" empty={_('Nothing to do')} defaultType="todo"
              defaultState="todo" showUser={false} />
</div>

<style>
  .mine {
    padding: 1rem;
    max-width: 56rem;
    height: 100%;
    overflow-y: auto;
  }
  h2 {
    font-size: 1.125rem;
    font-weight: 600;
    margin: 0 0 0.75rem;
    color: var(--kb-text);
  }
</style>
