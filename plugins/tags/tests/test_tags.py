"""
A tag vocabulary: one tag per name whatever its case, created from a name on save.

What has to hold: the name is stored trimmed and as first written, `name_key`
follows it on every write ignoring case, `_` and `-`, an empty name or one with
a comma is refused; the resolver turns names
into the keys of existing tags (Peach finds peach), creates the missing ones,
keeps ids as they are and the order of the list, and creates nothing for a user
who may not create tags.

The model is written here on the plugin's mixin, without building an application.

    (cd server && uv run pytest -q ../commons/plugins/tags/tests)
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base

from kitebase import access
from kitebase.transforms import ValidationError

MODEL = Path(__file__).resolve().parents[1] / 'model.py'
spec = importlib.util.spec_from_file_location('tags_model_under_test', MODEL)
tags = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tags)

Base = declarative_base()


class Tag(Base, tags.TagVocabulary):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False)
    name_key = Column(String(60), unique=True)


REF = SimpleNamespace(name='tags')


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def add(session, name):
    tag = Tag(name=name)
    session.add(tag)
    session.flush()
    return tag


# ── The vocabulary ────────────────────────────────────────────────────────────

def test_the_name_keeps_its_case_and_loses_its_extra_spaces(session):
    tag = add(session, '  Italian   Literature ')
    assert (tag.name, tag.name_key) == ('Italian Literature', 'italian literature')


def test_the_key_follows_the_name_when_it_is_corrected(session):
    tag = add(session, 'peach')
    tag.name = 'Peach'
    session.flush()
    assert (tag.name, tag.name_key) == ('Peach', 'peach')


def test_two_spellings_of_one_name_are_one_tag(session):
    add(session, 'Peach')
    with pytest.raises(IntegrityError):
        add(session, 'PEACH ')


def test_underscore_and_hyphen_are_spaces_to_the_key(session):
    tag = add(session, 'Italian-literature')
    assert (tag.name, tag.name_key) == ('Italian-literature', 'italian literature')
    with pytest.raises(IntegrityError):
        add(session, 'italian_literature')


def test_a_comma_in_the_name_is_refused(session):
    with pytest.raises(ValidationError):
        add(session, 'fiction, horror')


def test_an_empty_name_is_refused(session):
    with pytest.raises(ValidationError):
        add(session, '   ')


# ── The resolver ──────────────────────────────────────────────────────────────

def resolve(session, values):
    return tags.TagNames.resolve(session, Tag, REF, values)


def test_it_applies_to_the_vocabularies_only():
    assert tags.TagNames.applies_to(Tag)
    assert not tags.TagNames.applies_to(type('Other', (), {}))


def test_a_name_finds_the_tag_whatever_its_case(session):
    peach = add(session, 'Peach')
    assert resolve(session, ['PEACH', ' peach ']) == [peach.id, peach.id]
    assert session.query(Tag).count() == 1


def test_a_missing_name_is_created_and_ids_stay_where_they_were(session):
    plum = add(session, 'Plum')
    keys = resolve(session, [plum.id, 'Mango'])
    mango = session.query(Tag).filter_by(name_key='mango').one()
    assert keys == [plum.id, mango.id]
    assert mango.name == 'Mango'


def test_a_hyphen_finds_the_tag_written_with_a_space(session):
    tag = add(session, 'Italian literature')
    assert resolve(session, ['italian_literature', 'Italian-Literature']) == [tag.id, tag.id]


def test_a_name_with_a_comma_is_refused_on_the_field(session):
    with pytest.raises(ValidationError) as refused:
        resolve(session, ['fiction, horror'])
    assert 'tags' in refused.value.errors


def test_an_empty_name_in_the_list_is_dropped(session):
    assert resolve(session, ['  ']) == []


def test_without_the_permission_nothing_is_created(session, monkeypatch):
    peach = add(session, 'Peach')
    monkeypatch.setattr(access, 'can', lambda permission: permission != 'Tag.create')
    assert resolve(session, ['peach']) == [peach.id]        # an existing one is fine
    with pytest.raises(ValidationError):
        resolve(session, ['peach', 'Mango'])
    assert session.query(Tag).count() == 1
