"""
Kitebase records in AndRep templates: the acceptance tests of the record views.

A template reads the declared fields of a SQLAlchemy record — columns and
relations — and nothing else.  The views live in AndRep (andrep.adapters, and
andrep.adapters.sqlalchemy); these tests are skipped until the installed
AndRep has them, and must pass before the plugin relies on them.
"""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytest.importorskip("andrep.adapters.sqlalchemy",
                    reason="the installed AndRep has no record views (andrep.adapters)")

from sqlalchemy import ForeignKey, Numeric, String, create_engine  # noqa: E402
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session,  # noqa: E402
                            mapped_column, relationship)

from andrep import AndRepRenderer, RecordView, register_view  # noqa: E402
from andrep.adapters import VALUE  # noqa: E402
from andrep.adapters.sqlalchemy import SQLAlchemyView  # noqa: E402
from andrep.variables import _adapters  # noqa: E402
from helpers import emitted_values, make_template  # noqa: E402


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "author"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    books: Mapped[list["Book"]] = relationship(back_populates="author")


class Book(Base):
    __tablename__ = "book"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("author.id"))
    author: Mapped[Author | None] = relationship(back_populates="books")

    @property
    def label_text(self):                      # a property: not a field
        return f"{self.title} ({self.price})"

    def discount(self, pct):                   # a method: not a field
        return self.price * (100 - pct) / 100


class Unmapped:
    """Something that is not data and has no adapter."""


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        tolkien = Author(id=1, name="Tolkien")
        s.add_all([
            tolkien,
            Book(id=1, title="The Hobbit", price=Decimal("12.50"), author=tolkien),
            Book(id=2, title="Silmarillion", price=Decimal("18.00"), author=tolkien),
            Book(id=3, title="Anonymous", price=Decimal("5.00")),
        ])
        s.commit()
        # Flask-SQLAlchemy style: a harmless-looking chain that ends in the engine
        Book.query = SimpleNamespace(session=s)
        yield s
        del Book.query


@pytest.fixture(autouse=True)
def views():
    """Register the SQLAlchemy view for the test, then restore the registry."""
    saved = dict(_adapters)
    register_view(Base, SQLAlchemyView)
    yield
    _adapters.clear()
    _adapters.update(saved)


def values(cells, **scope):
    r = AndRepRenderer(make_template({"band": cells}))
    exec("r.emit('band')", {}, {"r": r, **scope})
    return emitted_values(r)


def is_marker(value, reason=""):
    return isinstance(value, str) and value.startswith("[#") and reason in value


# ---------------------------------------------------------------------------
# The data graph is readable
# ---------------------------------------------------------------------------

def test_columns(session):
    book = session.get(Book, 1)
    assert values(["[row.title]", "[row.price * 2]"], row=book) == ["The Hobbit", Decimal("25.00")]


def test_relation_to_one(session):
    assert values(["[row.author.name]"], row=session.get(Book, 1)) == ["Tolkien"]


def test_empty_relation(session):
    assert values(["[row.author.name if row.author else '-']"], row=session.get(Book, 3)) == ["-"]


def test_relation_to_many(session):
    author = session.get(Author, 1)
    [titles] = values(["[', '.join([b.title for b in a.books])]"], a=author)
    assert titles == "The Hobbit, Silmarillion"


def test_cycles_are_navigable(session):
    """Relations are read lazily: a cycle costs nothing until it is followed."""
    assert values(["[row.author.books[0].author.name]"], row=session.get(Book, 1)) == ["Tolkien"]


def test_workspace_accepts_records(session):
    r = AndRepRenderer(make_template({"band": ["[row.title]"]}))
    r["row"] = session.get(Book, 2)            # no TypeError: a view is data
    r.emit("band")
    assert emitted_values(r) == ["Silmarillion"]


def test_record_printed_as_a_whole(session):
    r = AndRepRenderer(make_template({"band": ["[row]"]}))
    r["row"] = session.get(Book, 2)
    r.emit("band")
    assert emitted_values(r) == [r._compiled[0]["values"][0]]
    assert str(emitted_values(r)[0]) == "Book(2)"
    assert "Book(2)" in r.to_json()           # compiled records stay serializable
    json.loads(r.to_json())


# ---------------------------------------------------------------------------
# Nothing but the data graph
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr, reason", [
    ("row.query.session", "Book.query is not a field"),
    ("row.metadata", "Book.metadata is not a field"),
    ("row.registry", "Book.registry is not a field"),
    ("row.label_text", "Book.label_text is not a field"),
    ("row.discount(10)", "Book.discount is not a field"),
    ("row.author.metadata.tables", "Author.metadata is not a field"),
    # the view's own API is not reachable from a template
    ("row.fields", "Book.fields is not a field"),
    ("row.label", "Book.label is not a field"),
    ("row.safe_methods", "Book.safe_methods is not a field"),
    ("row.extra_fields", "Book.extra_fields is not a field"),
    # refused by the expression check, before any evaluation
    ("row._record", "attribute '_record' is not allowed"),
    ("row._sa_instance_state", "attribute '_sa_instance_state' is not allowed"),
    ("row.__class__", "attribute '__class__' is not allowed"),
])
def test_only_fields(session, expr, reason):
    [value] = values([f"[{expr}]"], row=session.get(Book, 1))
    assert is_marker(value, reason), value


def test_view_is_read_only(session):
    view = SQLAlchemyView(session.get(Book, 1))
    with pytest.raises(AttributeError):
        view.title = "changed"


def test_related_record_without_adapter(session, monkeypatch):
    """A field holding something that is not data shows a marker, as a local does."""
    class Odd(SQLAlchemyView):
        extra_fields = {"odd": VALUE}
    register_view(Base, Odd)
    monkeypatch.setattr(Book, "odd", Unmapped(), raising=False)
    [value] = values(["[row.odd]"], row=session.get(Book, 1))
    assert is_marker(value, "Unmapped")


# ---------------------------------------------------------------------------
# What a view's author may add
# ---------------------------------------------------------------------------

def test_extra_fields(session):
    class Books(SQLAlchemyView):
        extra_fields = {"label_text": VALUE}
    register_view(Base, Books)
    assert values(["[row.label_text]"], row=session.get(Book, 1)) == ["The Hobbit (12.50)"]


def test_safe_methods_results_are_data(session):
    class Books(SQLAlchemyView):
        safe_methods = frozenset({"discount"})
    register_view(Base, Books)
    assert values(["[row.discount(10)]"], row=session.get(Book, 2)) == [Decimal("16.2")]


def test_custom_view_for_another_orm():
    """RecordView is ORM-agnostic: fields() comes from the ORM's metadata."""
    class Record:
        _fields = {"code": VALUE}

        def __init__(self, code):
            self.code = code
            self.secret = "s3cr3t"

    class RecordFields(RecordView):
        __slots__ = ()

        @classmethod
        def fields(cls, record):
            return record._fields

    register_view(Record, RecordFields)
    assert values(["[row.code]", "[row.secret]"], row=Record("A1"))[0] == "A1"
    assert is_marker(values(["[row.secret]"], row=Record("A1"))[0], "not a field")


def test_safe_method_arguments_are_data_at_any_depth(session):
    """A callable hidden in a container is refused like a bare one."""
    class Books(SQLAlchemyView):
        safe_methods = frozenset({"discount"})
    register_view(Base, Books)
    book = session.get(Book, 2)
    for expr in ("row.discount(stash.append)", "row.discount([stash.append])",
                 "row.discount({'k': stash.append})", "row.discount(pct=(1, stash.append))"):
        [value] = values([f"[{expr}]"], row=book, stash=[])
        assert is_marker(value, "arguments must be data"), (expr, value)


# ---------------------------------------------------------------------------
# Registration and identity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("view", [lambda obj: obj, dict, SQLAlchemyView(None)])
def test_register_view_takes_a_view_class(view):
    with pytest.raises(TypeError):
        register_view(Base, view)


def test_views_of_the_same_record_are_equal(session):
    hobbit, silmarillion = session.get(Book, 1), session.get(Book, 2)
    assert values(["[row.author == prev.author]", "[row.author == row]", "[row == prev]"],
                  row=hobbit, prev=silmarillion) == [True, False, False]
    views = {SQLAlchemyView(hobbit.author), SQLAlchemyView(silmarillion.author)}
    assert len(views) == 1
