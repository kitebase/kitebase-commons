# jobs

Long work that says where it is, and can be stopped where it allows.

The code that works calls `kitebase.notify`; with this plugin the person who
started it sees the line beside the status bar, with a counter and a Cancel
where the work allows it. Without the plugin the same calls go to the log.

```python
from kitebase.notify import notify

notify(f'Fetching description of {book.title}')            # a line

for i, book in enumerate(books):                            # a counter, and a
    notify('Fetching descriptions', done=i, total=len(books),  # phase that may stop
           cancellable=True)
    ...
```

## Stopping

Cancelling is the choice of who writes the work, per phase: the default is
not cancellable, and a phase says `cancellable=True` where stopping leaves
nothing half done. A cancel asked in a phase that is not cancellable waits
("Cancelling...") for the first one that is; there `notify()` raises
`kitebase.errors.Cancelled`. What was done stays done: a work that must undo
does it in `except Cancelled`, a work that stops politely catches it and says
how far it got.

## How

Each work is a lease of `transient` (`work:<request id>`), shown to the
person who started it: the last state, never a log. The dispatcher closes it
when the request ends; it expires by itself if nothing renews it.

The client component (`jobs.status`, mounted beside the status line by
`chrome_areas.yaml`) asks `jobs_poll`, and the answer says when to ask again:
soon while a work is open, slowly otherwise. A call of the client still
waiting after a second makes it look at once; a hidden tab does not poll.
The polls are `quiet`: neither the kitebase log nor the access log lists them.

## Settings

The `jobs:` section of the application's `config.yaml`, all optional:

```yaml
jobs:
  work_ttl: 120     # seconds a work lives without a notify
  poll_slow: 30     # seconds between two polls with nothing open
  poll_fast: 1.5    # seconds between two polls while a work is open
```

## Limits

A work runs in the request that starts it: the proxy must let it last
(`proxy_read_timeout` for nginx), and the web server must have threads to
spare for the polls while it runs (gunicorn `gthread`, waitress `threads`).
Code that never calls `notify()` cannot be stopped from here.
