"""
The duplicate codes of a partner: asked about, never refused.

What has to hold: a VAT number or a tax code another partner holds is a
question, naming who holds it and saying when that row is archived; a yes
saves; an empty code, a code nobody else holds and a code an update leaves
unchanged ask nothing; the row being updated is not its own duplicate.

The rule runs through `flow.judge`, as the db endpoint runs it, on a model
written here: the plugin's rule, without building an application.

    (cd commons/demo && uv run pytest -q ../plugins/partners/tests)
"""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Boolean, Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base

import kitebase.utils
from kitebase import flow

RULES = Path(__file__).resolve().parents[1] / 'rules.py'

Base = declarative_base()


class Partner(Base):
    __tablename__ = 'partners'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    vat_number = Column(String)
    tax_code = Column(String)
    active = Column(Boolean, default=True)

    @property
    def is_archived(self):
        return self.active is False


class FakeApp:
    def __init__(self, engine):
        self.engine = engine
        self.models = {'Partner': Partner}

    def get_session(self):
        return Session(self.engine)


@pytest.fixture(autouse=True)
def app(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all([Partner(id=1, name='Riverside Hardware', vat_number='IT001', tax_code='RSD'),
                   Partner(id=2, name='Old Riverside', vat_number='IT002', active=False)])
        s.commit()
    monkeypatch.setattr(kitebase.utils, 'get_app', lambda: FakeApp(engine))
    # The plugin's file, as the loader imports it: the rule registers itself
    spec = importlib.util.spec_from_file_location('partners_rules', RULES)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    yield


def judge(mode, record, original=None, answers=None):
    return flow.judge('Partner', mode, record, original, answers)


def test_a_vat_number_already_held_is_asked_about_with_the_holder():
    _ctx, refusal = judge('insert', {'name': 'Riverside', 'vat_number': 'IT001'})

    assert refusal['code'] == 409
    question = refusal['$flow']['ask']
    assert question['key'] == 'partner_duplicate_codes'
    assert question['text'] == 'VAT number IT001 is already held by Riverside Hardware.'


def test_an_archived_holder_is_said_to_be_archived():
    _ctx, refusal = judge('insert', {'name': 'New', 'vat_number': 'IT002'})

    assert 'Old Riverside (archived)' in refusal['$flow']['ask']['text']


def test_both_codes_are_said_in_one_question():
    _ctx, refusal = judge('insert', {'name': 'New', 'vat_number': 'IT001', 'tax_code': 'RSD'})

    assert refusal['$flow']['ask']['text'] == (
        'VAT number IT001 is already held by Riverside Hardware. '
        'Tax code RSD is already held by Riverside Hardware.')


def test_a_yes_saves_and_a_no_does_not():
    record = {'name': 'Riverside', 'vat_number': 'IT001'}
    assert judge('insert', record, answers={'partner_duplicate_codes': True})[1] is None
    assert judge('insert', record, answers={'partner_duplicate_codes': False})[1]['code'] == 422


@pytest.mark.parametrize('record', [
    {'name': 'New'},                                   # no codes at all
    {'name': 'New', 'vat_number': '', 'tax_code': None},
    {'name': 'New', 'vat_number': 'IT999'},            # held by nobody
])
def test_nothing_is_asked_when_no_other_row_holds_the_code(record):
    assert judge('insert', record)[1] is None


def test_an_update_is_not_its_own_duplicate():
    row = {'id': 1, 'name': 'Riverside Hardware', 'vat_number': 'IT001', 'tax_code': 'RSD'}
    assert judge('update', {**row, 'name': 'Riverside Hardware Ltd'}, original=row)[1] is None


def test_an_unchanged_duplicate_is_not_asked_again_at_every_save():
    row = {'id': 3, 'name': 'Twin', 'vat_number': 'IT001'}
    assert judge('update', {**row, 'name': 'Twin Ltd'}, original=row)[1] is None
    assert judge('update', {**row, 'vat_number': 'IT002'}, original=row)[1]['code'] == 409


def test_a_delete_asks_nothing():
    assert judge('delete', {'id': 1, 'vat_number': 'IT001'}, original={'id': 1})[1] is None
