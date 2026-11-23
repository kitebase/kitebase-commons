# transient

What expires by itself: leases, rows that say who holds what, since when and
alive until when.

Transient as the `transient` fields of a form: what is kept here never becomes
durable. That is the whole contract, and what keeps the table cheap. A row
lost costs a line on a screen, never data: cleaning is deleting what expired,
and a migration may empty the table, because the holders renew their rows by
themselves.

A base, not a feature: nothing here shows on a screen. Other plugins build on
it with `depends_on: [transient]`:

| plugin | its leases |
|---|---|
| `jobs` | a work in progress: what it is doing, a counter, whether it may stop |
| `concurrency` | a person editing a document |

## The table

`Lease`, one row per holder and subject:

- **subject**: `model` and `record_id`, a document or empty (the empty string,
  not `NULL`: nulls never collide in a unique index);
- **holder**: `user:3`, `work:<key>`, the name of a process;
- **for whom**: `user_id`, `user_name`;
- **what it says**: `doing`, `done`, `total`, `cancellable`, `cancel_requested`;
- **its life**: `since`, `last_activity`, `expires_at`.

## The API

Every function works on the caller's session and leaves the commit to it.

```python
from transient import lease

with app.get_session() as session:
    lease.hold(session, 'work:42', ttl=120, user_id=3, doing='Reading orders')
    session.commit()

lease.live(session, user_id=3)                    # what a person has open
lease.live(session, model='Order', record_id=7)   # who is on a document
lease.mark(session, 'work:42', cancel_requested=True)   # without renewing it
lease.release(session, 'work:42')
lease.sweep(session)                              # what expired, deleted
```

`hold` takes the lease or renews it, keeping `since`. Readers see live leases
only, so an expired row is gone for everybody before the sweep deletes it.
