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

Every form of a page is read and written as a tree, with or without
collections: they all carry the version.

## Who else is editing

A version protects the data; a presence tells who is working on a document
before anyone saves. On top of every form of a table (`form_areas.yaml`) the
component `concurrency.presence` says *"Ann is editing this document, for 25
minutes, idle for 12 minutes"*, and nothing when nobody is there. It is advice,
never a lock: whoever opens decides whether to go on, and the version still
guards the save.

- **A person shows up at the first change**, not when the form opens: whoever
  only looks writes nothing.
- **The activity renews it**: a field changed, a frame of the form opened or
  closed, the window coming back to the front. At most one call a minute, and
  only after something happened: whoever stands still makes no traffic.
- **It expires by itself**: without activity for 15 minutes the person leaves
  the list. Releasing at the save or the close is a courtesy; a tab closed from
  its handle releases nothing, and nothing is wrong for that.
- **Every answer brings the news**: who else is there, and the version of the
  document. A newer version than the form's is said at once: *"someone else
  saved meanwhile: when you save, your changes will be merged with theirs"*.

A long procedure says what it is doing, and whoever opens the document sees it
as they would see a person:

```python
from concurrency.presence import editing

with editing('Order', 7, doing='Shipping in progress'):
    ...
```

`acquire` and `release` do the same in two steps, with a longer lease if the
procedure needs one. The endpoints of the form are `presence_touch`,
`presence_who` and `presence_release`, for whoever may read the document.

The times, in the application's `config.yaml`:

```yaml
concurrency:
  presence_ttl: 900       # seconds without activity before a person leaves the list
  touch_every: 60         # at most one renewal a form sends per this many seconds
  marker_horizon: 86400   # markers untouched this long are swept
```

Expired presences and old markers are swept now and then by a request, with no
scheduler: a marker swept while someone still holds its version makes their
next save a conflict, never a loss.
