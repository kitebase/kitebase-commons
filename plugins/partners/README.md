# partners

One table for every subject the company deals with — customers, suppliers,
members, employees, and the contacts and addresses that hang off them.

The same person or firm is routinely more than one of those. Separate tables per
role would mean entering them twice and letting their addresses drift apart, so
`Partner` is a single table and what separates the roles is the **view**.

## Using it from an application

**Declare the role codes.** They are rows of `PartnerRole`, declared by the
application in its `data:` section — the shared plugin cannot know them, because
a role only exists once some view filters on it and some default stamps it.

**One view per role**, each with a fixed `domain` on `roles` and `defaults` that
stamps the role on insert:

```yaml
customer_list:
  content:
    source:
      model: Partner
      domain: [{roles: [has, C]}]   # holds the role C
      defaults: {roles: [C]}        # a record added here is born a customer
```

**Plus one unfiltered view.** The role views hide whoever does not hold the
role, so without a registry view there is nowhere to find an existing subject
and give it a second role — and people duplicate instead.

**Add role-specific columns from the plugin that needs them**, through
deep_merge:

```yaml
tables:
  Partner:
    columns:
      - name: credit_limit
        type: Money
```

The table is meant to be wide and mostly nullable. Satellite tables would cost a
join and a sub-form for every role, and the columns that stay empty cost nothing
in SQL.

> **Invariant:** role-specific columns are **always nullable in the schema**.
> Requiredness belongs to the view, as a reactive `required`. A NOT NULL column
> belonging to one role would stop the records of every other role from being
> created at all.

## Roles as a set of codes

`Partner.roles` is a `ShortSet`, common's type on the core's `CodeSet`: a list
of codes, `["C", "S"]`, in Python and on the wire, stored as `",C,S,"`. A view
filters on one with `has`, which can never match `C` inside `CO`. The column names where its codes come from
(`choices_endpoint: partner_roles`, the rows of `PartnerRole` in their order):
the form picks them from a popup with a check per role and shows the codes
alone, and the filters of a list ask "has any of" with the same popup. A code
that is not one of those rows is refused on save.

A set rather than one column per role, because a new role must be a row in
`PartnerRole` and not an ALTER on a table every application shares. A set rather
than a single code, because a subject really is customer and supplier at once.

The column is not indexed: a `LIKE` with a leading wildcard would not use one.

## Children: contacts and addresses

A row with `parent_id` set hangs off another subject, and `usage` says what it
is — `contact`, `invoice`, `delivery`, `operational`.

This is why there is no address table: a child row already carries a full
address, a name of its own and its own channels, which is exactly what a
delivery address or a contact person needs. The main address and the primary
channels are inline on the subject, so a list or an export needs no join.

`usage` is a plain column and not a registry like `PartnerRole`, because the
code branches on those values — invoice printing looks for `invoice` — and a
value no code knows about is inert. A registry would promise an extensibility
that does not exist, and charge a join on every child row for it.

## Person or organization

`kind` is the one discriminator everything shares: the form reads it to render
one name box or two, correspondence and privacy obligations follow it. It is a
closed set owned by the code — the opposite of `roles`.

Write tests on the person side, `kind == 'person'`, so that kinds added later
(public body, group) fall among the non-persons, where a rule written before
they existed still puts them. A sole trader is a `person`: legally it is one,
and it invoices as "Smith, John" whatever the shop sign reads.

For a person, `name` is `"Surname, Given"`. The comma is what makes the split
deterministic in both directions, which is why the parts are not separate
columns: composing is always possible, and with the comma so is decomposing.

Legal form (Ltd, Inc, association) is deliberately not a value of `kind`: it is
a property *of* an organization, not an alternative to being one, and its values
are an open set that varies by country. It gets its own column when an
application needs it — as a lookup whose rows state the `kind` they imply.

## Identification and duplicates

`vat_number` and `tax_code` live here rather than in a fiscal plugin because
they identify the subject the way the name does, and because the duplicate check
on save is a property of the registry itself. What is country-specific — the
checksum, the format, which of the two is mandatory — is validation, and a
plugin adds that without owning the column.

Neither is unique. Foreign subjects have no domestic VAT number, private
individuals have none at all, and duplicates legitimately exist until someone
unifies them. Both are indexed, and they are what a duplicate warning is built
on.

## Deliberately not here

**No registry-wide `code`.** A subject holds several roles at once, so one
column could not carry both the member number and the employee number of the
same person. Role plugins declare their own, and they are separate columns
precisely because they are separate things.

**No registry data of a natural person** — birth date, citizenship, documents.
Those are in the `persons` plugin. The line is not "does it concern a person"
but what the application does with them: everyone *writes to* people, since a
company's contact is one, and title, gender and the channels serve that from
here; only some applications *keep a registry* of them, and only those take
`persons`. The privacy weight falls on the same side of that line.

**No `merged_into` pointer.** A column that means something only together with
the command maintaining it belongs with that command; here it would be inert,
and an inert column invites a half-implemented merge. It comes back, by
deep_merge, with the plugin that can actually unify duplicates.

## See also

- `persons` — the natural-person facet: birth date, citizenship.
- `docs/pending/party_model.md` — the design record: what was considered and
  rejected on the way here.
