# concurrency

Two saves of one document never overwrite each other in silence.

A document opened in a form carries a version. A save that brings an older
version than the stored one is refused (409), nothing of it written, and the
answer holds the document as it is now. Nobody is ever locked out: whoever
leaves a form open and walks away blocks nobody, and finds the conflict when
they come back and save.

## What it covers

- **The document is the aggregate.** Its rows are part of it through the
  foreign keys declared `owned`: a change to a row of a collection, at any
  depth, is a change to the document. A table that is not owned (a loan of a
  book) is a document of its own.
- **Every write through the ORM session renews the version**: the forms,
  `db`, `save_tree`, the procedure of a plugin that loads rows and commits. The
  plugin that writes needs to know nothing about this one.
- **A save is checked only when it brings a version**: a form that opened the
  document, an API client that read it. A procedure that reads and writes in
  one transaction is not checked, and still renews the version.
- **Writes the session does not see** (a bulk `update`, SQL) renew nothing on
  their own: the procedure names the documents it touched.

```python
from concurrency.markers import touched

session.query(OrderLine).filter(...).update({...})
touched(session, [('Order', 7)])        # committed with the session
```

## How

A table, `EditMarker`, holds one row per document opened in a form:
`(model, record_id, token)`. The core's tree hooks hand the token out with
the document (`$version` on the root of `load_tree`) and check it before the
save writes anything; a listener on the session renews it on every flush that
touches a document with a marker. Documents nobody opened have no marker and
pay nothing.

Forms without collections save through `db`, which carries no version: they
are not checked yet.
