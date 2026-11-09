# tags

Free labels on any table, from a vocabulary the users grow as they type.

A tag only classifies and filters: nothing computes on it. A set of values
that some mechanism reads (roles that grant permissions, kinds that change
behaviour) is a `CodeSet` or a column of its own, not a tag. The two can live
on the same table.

## Using it from an application

Each tagged table gets a vocabulary and a junction, written out in its YAML:

```yaml
tables:
  BookTag:
    name: book_tags
    mixins: [TagVocabulary]

  BookTagLink:
    name: book_tag_links
    many_to_many:
      target1: { table: Book.id, column: book_id, collection: tags, field: true }
      target2: { table: BookTag.id, column: tag_id }
```

`Book.tags` is then a field of the book: a list of tag ids on the wire, shown as
badges in forms and lists, filtered with *has any / all / none of*. See
`field: true` in `PLUGIN_MODEL.md` § 4.6 of the server docs.

Two tables that should share their tags point their junctions at the same
vocabulary. Add `Archivable` to the vocabulary's mixins to retire tags without
taking them off the rows that hold them.

## What the plugin does

- **One tag per name.** `name_key` is the name folded for comparison: case,
  extra spaces, `_` and `-` make no difference, so *Italian literature*,
  *italian_literature* and *Italian-Literature* are one tag. The name keeps the
  spelling of whoever wrote it first; correct it once in the vocabulary.
- **No commas in a name**: the comma separates tags wherever a list is typed.
- **Names on save.** A list written to the field may hold names beside ids,
  `[3, 7, "Peach"]`: a name finds the tag it folds to, or becomes a new tag in
  the same transaction, when the user may create rows of the vocabulary
  (`BookTag.create`). Nothing is created before the record is saved.

## Access

Writing the tags of a book is `Book.update`; reading and filtering them asks
for `Book.read` and for the vocabulary (`BookTag.read`, or its label). Creating
a tag by typing it is `BookTag.create`.
