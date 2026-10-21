"""The registered report loops, and what a loop needs to read its records.

A report is a name bound to a loop: the function that reads the data and
emits the bands. The client names a report, never a Python module, so the
registry is the only way from a request to the code that runs.

    @report('sales.invoice', table='Invoice', label='Invoice', renderer=InvoiceRenderer)
    def invoice(r, params):
        for row in load_records('Invoice', params['ids'], load=['lines']):
            r.emit('band_desc')

The name is `domain.name`, and the domain is the plugin the loop lives in: the
plugin `sales` registers `sales.*` only. Registering a name twice is an error
unless the second one says `replace=True`, which is how a derived plugin swaps
a loop. One loop may be registered under several names, each with fixed
`params` merged into the ones it receives.

`table` puts the report in the catalog of that table: what the Print button of
its views offers, under `label`. A report without a table is reached only by
name, as the last step of a chain.
"""
import contextvars
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Sequence, Union

from andrep import AndRepRenderer

INPUTS = ('view', 'none')
ON_EMPTY = ('all', 'row')

# Ids per query: small enough for any database's limit on bound parameters.
BLOCK = 500


@dataclass(frozen=True)
class Report:
    name: str
    loop: Callable
    renderer: type = AndRepRenderer
    input: str = 'view'           # 'view': the rows of the view; 'none': it does not look at the UI
    on_empty: str = 'all'         # with no ticked rows: 'all' visible rows, or the current 'row'
    options: Optional[str] = None  # id of the form of its options
    params: Dict[str, Any] = field(default_factory=dict)
    table: Optional[str] = None    # the table whose Print button offers it
    label: Optional[str] = None    # what the Print button shows; default the short name

    @property
    def domain(self) -> str:
        return self.name.split('.', 1)[0]

    @property
    def short_name(self) -> str:
        return self.name.split('.', 1)[1]

    @property
    def title(self) -> str:
        return self.label or self.short_name


_REPORTS: Dict[str, Report] = {}


def register(name: str, loop: Callable, *, domain: str, replace: bool = False,
             renderer: type = AndRepRenderer, input: str = 'view', on_empty: str = 'all',
             options: Optional[str] = None, params: Optional[Dict[str, Any]] = None,
             table: Optional[str] = None, label: Optional[str] = None) -> Report:
    """Bind `name` to `loop`. Raises ValueError on a name the registry refuses."""
    prefix, dot, rest = name.partition('.')
    if not dot or not prefix or not rest:
        raise ValueError(f"report name {name!r} is not 'domain.name'")
    if prefix != domain:
        raise ValueError(f"report {name!r} registered by plugin {domain!r}: "
                         f"its name must start with '{domain}.'")
    if input not in INPUTS:
        raise ValueError(f"report {name!r}: input must be one of {INPUTS}, not {input!r}")
    if on_empty not in ON_EMPTY:
        raise ValueError(f"report {name!r}: on_empty must be one of {ON_EMPTY}, not {on_empty!r}")
    if not (isinstance(renderer, type) and issubclass(renderer, AndRepRenderer)):
        raise ValueError(f"report {name!r}: renderer must be an AndRepRenderer subclass")

    existing = _REPORTS.get(name)
    if existing is not None and not replace and not _same_loop(existing.loop, loop):
        raise ValueError(f"report {name!r} is already registered by "
                         f"{existing.loop.__module__}.{existing.loop.__qualname__}: "
                         f"pass replace=True to replace it")

    found = _REPORTS[name] = Report(name, loop, renderer, input, on_empty, options,
                                    dict(params or {}), table, label)
    return found


def _same_loop(a: Callable, b: Callable) -> bool:
    """The same function defined again: its module imported a second time."""
    return (a.__module__, a.__qualname__) == (b.__module__, b.__qualname__)


def report(name: str, **declarations) -> Callable[[Callable], Callable]:
    """Register the decorated loop under `name`; see `register` for the rest.

    The domain is the plugin the loop's module belongs to: kitebase imports a
    plugin's files as `<plugin>.<module>`.
    """
    def decorator(loop: Callable) -> Callable:
        domain = loop.__module__.split('.', 1)[0] if '.' in loop.__module__ else ''
        register(name, loop, domain=domain, **declarations)
        return loop
    return decorator


def get(name: str) -> Optional[Report]:
    return _REPORTS.get(name)


def all_reports() -> Dict[str, Report]:
    return dict(_REPORTS)


def for_table(table: str) -> list:
    """The catalog of `table`: its reports, in the order they were registered."""
    return [r for r in _REPORTS.values() if r.table == table]


# ── Records ───────────────────────────────────────────────────────────────────

# The session of the report being run, opened by reports.run around the loop.
current_session: contextvars.ContextVar = contextvars.ContextVar('reports_session', default=None)


def load_records(model: Union[str, type], ids: Sequence[Any],
                 load: Iterable[str] = (), session=None) -> Iterator[Any]:
    """
    The records of `ids`, in the order of `ids`, read in blocks.

    `load` names the relations the template will read, as dotted paths
    (`'loans.library_user'`): they are loaded with the block instead of one
    query per row. A relation left out is still read, only more slowly. An id
    that matches no record is skipped.
    """
    import kitebase.utils
    from sqlalchemy import inspect
    from sqlalchemy.orm import selectinload

    if isinstance(model, str):
        found = kitebase.utils.get_app().models.get(model)
        if found is None:
            raise ValueError(f"unknown table {model!r}")
        model = found
    session = session if session is not None else current_session.get()
    if session is None:
        raise RuntimeError('load_records outside a report: pass a session')

    [pk] = inspect(model).primary_key
    options = [_load_path(model, path, selectinload) for path in load]

    for start in range(0, len(ids), BLOCK):
        block = list(ids[start:start + BLOCK])
        rows = session.query(model).options(*options).filter(pk.in_(block)).all()
        by_id = {getattr(row, pk.key): row for row in rows}
        for i in block:
            row = by_id.get(i)
            if row is not None:
                yield row


def _load_path(model: type, path: str, selectinload):
    """`'loans.library_user'` as a chain of selectinload."""
    from sqlalchemy import inspect

    option = None
    current = model
    for name in path.split('.'):
        relation = inspect(current).relationships.get(name)
        if relation is None:
            raise ValueError(f"{current.__name__} has no relation {name!r} (in load={path!r})")
        attr = getattr(current, name)
        option = selectinload(attr) if option is None else option.selectinload(attr)
        current = relation.mapper.class_
    return option
