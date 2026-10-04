<script lang="ts">
  /**
   * Partners plugin — person name editor. PLACEHOLDER.
   *
   * Registry ID: partners.personname
   * Lives next to the plugin it belongs to (model.yaml, config.yaml), so any
   * application whose config.yaml lists this root gets it with no registration.
   *
   * What the real widget will do: `Partner.name` stores one string, and for a
   * person that string is "Surname, Given" — the comma is what makes the split
   * deterministic in both directions, which is why the parts are not columns.
   * This placeholder already composes and decomposes around it; what it does
   * not do is anything a widget must do to be one — bind to a form field,
   * validate, react to `kind`, or feed the search index.
   */

  interface Props {
    /** The stored value: "Surname, Given". */
    value?: string;
    /** Notified on every edit, with the recomposed value. */
    onchange?: (value: string) => void;
  }

  let { value = '', onchange }: Props = $props();

  // Decompose on the first comma only: a surname may contain one, a given name
  // does not follow it. Both sides trimmed, so "Smith,John" reads the same.
  const split = (v: string) => {
    const i = v.indexOf(',');
    return i < 0
      ? { surname: v.trim(), given: '' }
      : { surname: v.slice(0, i).trim(), given: v.slice(i + 1).trim() };
  };

  let parts = $state(split(value));

  // Compose back: no given name means no comma, so a one-part name survives a
  // round trip unchanged instead of picking up a stray separator.
  const composed = $derived(
    parts.given ? `${parts.surname}, ${parts.given}` : parts.surname
  );

  function edit(field: 'surname' | 'given', v: string) {
    parts[field] = v;
    onchange?.(composed);
  }
</script>

<div
  class="rounded-lg border p-4"
  style="border-color: var(--kb-border); background: var(--kb-surface)"
>
  <div class="mb-3 flex items-baseline gap-2">
    <h3 class="text-sm font-semibold" style="color: var(--kb-text)">Person name</h3>
    <span class="text-xs" style="color: var(--kb-text-subtle)">partners.personname · placeholder</span>
  </div>

  <div class="flex flex-wrap gap-3">
    <label class="flex flex-1 flex-col gap-1">
      <span class="text-xs" style="color: var(--kb-text-muted)">Surname</span>
      <input
        class="rounded border px-2 py-1 text-sm"
        style="border-color: var(--kb-border-input); background: var(--kb-bg); color: var(--kb-text)"
        value={parts.surname}
        oninput={(e) => edit('surname', e.currentTarget.value)}
      />
    </label>

    <label class="flex flex-1 flex-col gap-1">
      <span class="text-xs" style="color: var(--kb-text-muted)">Given name</span>
      <input
        class="rounded border px-2 py-1 text-sm"
        style="border-color: var(--kb-border-input); background: var(--kb-bg); color: var(--kb-text)"
        value={parts.given}
        oninput={(e) => edit('given', e.currentTarget.value)}
      />
    </label>
  </div>

  <p class="mt-3 text-xs" style="color: var(--kb-text-subtle)">
    stored as <code style="color: var(--kb-text)">{composed || '—'}</code>
  </p>
</div>
