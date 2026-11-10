"""
The settings plugin on an application: catalog, provider, the two endpoints,
the token of the pages, and what `check` says about the catalog.

The application is built once for the module: the shared plugins common and
settings, plus `shop`, written here, which declares a group of settings and a
page whose form takes one of them as a default.

    (cd commons/demo && uv run pytest -q ../plugins/settings/tests)
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

import kitebase.plugins
import kitebase.source
import kitebase.utils
from kitebase import settings as port
from kitebase.diagnostics import run_checks
from kitebase.endpoint_panels import get_page
from kitebase.server_utils import handle_generic_endpoint

COMMONS = Path(__file__).resolve().parents[2]

SHOP_SETTINGS = {'settings': {
    'shop': {
        'label': 'Shop',
        'help': 'How the shop proposes things',
        'items': [
            {'name': 'default_discount', 'type': 'Percent', 'default': 10,
             'help': 'Proposed for the lines of a new order'},
            {'name': 'greeting', 'type': 'ShortStr', 'default': 'Welcome',
             'help': 'The first line of a quote'},
            {'name': 'reminder_days', 'type': 'Json', 'default': [30, 60],
             'help': 'Days after the due date for each reminder'},
            {'name': 'open_on_sunday', 'type': 'Boolean', 'default': False,
             'help': 'Whether Sunday is a working day'},
        ],
    },
}}

SHOP_PAGES = {'pages': {'order_form': {'content': {
    'type': 'form',
    'source': {'defaults': {'discount': '$setting.shop.default_discount'}},
    'fields': [{'name': 'discount', 'type': 'Number'}],
}}}}


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('shopapp')
    shop = root / 'plugins' / 'shop'
    shop.mkdir(parents=True)
    (shop / 'config.yaml').write_text(yaml.safe_dump({'name': 'shop'}))
    (shop / 'settings.yaml').write_text(yaml.safe_dump(SHOP_SETTINGS, sort_keys=False))
    (shop / 'pages.yaml').write_text(yaml.safe_dump(SHOP_PAGES))
    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'shopapp',
        'plugins': [{'path': str(COMMONS), 'include': ['common', 'settings']}, 'plugins'],
        'db_engine': f'sqlite:///{root / "shop.sqlite"}',
    }))

    cwd = os.getcwd()
    os.chdir(root)
    try:
        pm = kitebase.plugins.PluginsManager()
        pm.load_config('config.yaml')
        kitebase.utils.register_standard_handlers(pm)
        pm.load_plugins()
        db = kitebase.utils.get_app()
        db.calc_db(pm)
        kitebase.source.Generator(db).generate(filename='shop_model.py')
        spec = importlib.util.spec_from_file_location('shop_model', root / 'shop_model.py')
        model = importlib.util.module_from_spec(spec)
        sys.modules['shop_model'] = model
        spec.loader.exec_module(model)
        db.initialize_db(pm.config['db_engine'], model)
        yield db
    finally:
        os.chdir(cwd)


@pytest.fixture(autouse=True)
def clean(app):
    """Each test starts from the catalog: no override."""
    with app.get_session() as s:
        s.query(app.models['Setting']).delete()
        s.commit()


def call(app, op, **data):
    return handle_generic_endpoint(app.dispatcher, op, data, {'username': 'tester', 'id': 7})


def by_name(result):
    return {i['name']: i for i in result['data']['items']}


# ── Reading ───────────────────────────────────────────────────────────────────

def test_a_key_without_a_row_has_the_default(app):
    assert port.get('shop.default_discount') == 10
    assert port.get('shop.reminder_days') == [30, 60]


def test_a_key_nobody_declared_is_an_error(app):
    with pytest.raises(KeyError):
        port.get('shop.nope')


def test_the_group_lists_its_items_in_the_declared_order(app):
    result = call(app, 'get_settings', group='shop')
    assert result['status'] == 'success', result
    assert result['data']['label'] == 'Shop'
    assert [i['name'] for i in result['data']['items']] == [
        'default_discount', 'greeting', 'reminder_days', 'open_on_sunday']
    assert by_name(result)['greeting'] == {
        'key': 'shop.greeting', 'name': 'greeting', 'type': 'ShortStr',
        'label': 'greeting', 'help': 'The first line of a quote',
        'default': 'Welcome', 'value': 'Welcome', 'set': False}


def test_an_unknown_group_is_a_404(app):
    assert call(app, 'get_settings', group='nowhere')['status_code'] == 404


# ── Writing ───────────────────────────────────────────────────────────────────

def test_a_changed_value_is_a_row_and_is_read_back(app):
    result = call(app, 'set_settings', group='shop', values={'default_discount': '12.5'})
    assert result['status'] == 'success', result
    assert result['data']['default_discount'] == 12.5     # the values, as a form expects
    item = by_name(call(app, 'get_settings', group='shop'))['default_discount']
    assert (item['value'], item['set']) == (12.5, True)
    assert port.get('shop.default_discount') == 12.5

    with app.get_session() as s:
        row = s.get(app.models['Setting'], 'shop.default_discount')
        assert (row.value, row.updated_by) == (12.5, 7)


def count(app):
    with app.get_session() as s:
        return s.query(app.models['Setting']).count()


def test_a_form_saved_unchanged_records_nothing(app):
    values = {i['name']: i['value'] for i in call(app, 'get_settings', group='shop')['data']['items']}
    call(app, 'set_settings', group='shop', values=values)
    assert count(app) == 0


def test_a_value_set_back_to_the_default_is_a_decision_and_stays(app):
    call(app, 'set_settings', group='shop', values={'greeting': 'Hello'})
    call(app, 'set_settings', group='shop', values={'greeting': 'Welcome'})
    item = by_name(call(app, 'get_settings', group='shop'))['greeting']
    assert (item['value'], item['default'], item['set']) == ('Welcome', 'Welcome', True)
    assert count(app) == 1


def test_a_later_default_reaches_only_what_was_not_set(app):
    call(app, 'set_settings', group='shop', values={'greeting': 'Hello'})
    call(app, 'set_settings', group='shop', values={'greeting': 'Welcome'})
    items = app.plugins.data['settings']['shop']['items']
    for item in items:
        if item['name'] in ('greeting', 'default_discount'):
            item['saved'] = item['default']
    try:
        for item in items:
            if item['name'] == 'greeting':
                item['default'] = 'Good morning'
            if item['name'] == 'default_discount':
                item['default'] = 15
        assert port.get('shop.greeting') == 'Welcome'          # set: it stays
        assert port.get('shop.default_discount') == 15         # not set: it follows
    finally:
        for item in items:
            if 'saved' in item:
                item['default'] = item.pop('saved')


def test_reset_makes_the_item_follow_the_catalog_again(app):
    call(app, 'set_settings', group='shop', values={'default_discount': 20})
    call(app, 'set_settings', group='shop', values={'default_discount': 20},
         reset=['default_discount'])
    item = by_name(call(app, 'get_settings', group='shop'))['default_discount']
    assert (item['value'], item['set']) == (10, False)
    assert count(app) == 0


def test_a_value_the_type_refuses_writes_nothing(app):
    result = call(app, 'set_settings', group='shop', values={
        'default_discount': '12.345',          # Percent: two decimals
        'greeting': 'x' * 40,                  # ShortStr: 32 characters
        'open_on_sunday': True,
        'nope': 1})
    assert result['status_code'] == 400, result
    assert set(result['data']['errors']) == {'default_discount', 'greeting', 'nope'}
    assert port.get('shop.open_on_sunday') is False


def test_a_json_value_is_kept_as_it_is(app):
    call(app, 'set_settings', group='shop', values={'reminder_days': [15, 30, 90]})
    assert port.get('shop.reminder_days') == [15, 30, 90]


# ── The form and the administrator's view ─────────────────────────────────────

def test_the_form_loads_and_saves_flat_values(app):
    """What DataForm does with `source.endpoint` and `save_endpoint`."""
    loaded = call(app, 'settings_values', group='shop')['data']
    assert loaded == {'default_discount': 10, 'greeting': 'Welcome',
                      'reminder_days': [30, 60], 'open_on_sunday': False}
    saved = call(app, 'set_settings', group='shop', data={**loaded, 'greeting': 'Hi'})
    assert saved['data'] == {**loaded, 'greeting': 'Hi'}
    assert count(app) == 1


def test_the_list_shows_every_item_and_the_orphans(app):
    call(app, 'set_settings', group='shop', values={'reminder_days': [7]})
    with app.get_session() as s:
        s.add(app.models['Setting'](key='gone.away', value=3))
        s.commit()
    listed = {r['id']: r for r in call(app, 'settings_list')['data']}
    assert listed['shop.reminder_days']['state'] == 'set'
    assert listed['shop.reminder_days']['value'] == '[7]'
    assert listed['shop.greeting']['state'] == 'default'
    assert listed['gone.away']['state'] == 'orphan'

    result = call(app, 'settings_drop_orphans')
    assert result['status'] == 'success', result
    assert 'gone.away' not in {r['id'] for r in call(app, 'settings_list')['data']}
    assert port.get('shop.reminder_days') == [7]        # a declared row stays


# ── The page token ────────────────────────────────────────────────────────────

def test_the_page_carries_the_value(app):
    call(app, 'set_settings', group='shop', values={'default_discount': 7})
    page = get_page({'id': 'order_form'})
    assert page['data']['content']['source']['defaults'] == {'discount': 7}


# ── check ─────────────────────────────────────────────────────────────────────

def test_the_application_checks_clean(app):
    issues = [i for i in run_checks(app) if i['severity'] in ('error', 'warning')]
    assert issues == []


def test_check_names_a_bad_catalog(app):
    data = app.plugins.data['settings']
    data['broken'] = {'items': [
        {'name': 'no_type', 'type': 'Nonsense', 'help': 'x'},
        {'name': 'bad_default', 'type': 'Percent', 'default': 'ten', 'help': 'x'},
        {'name': 'no_help', 'type': 'Integer', 'default': 1},
        {'name': 'typo', 'type': 'Integer', 'defualt': 1, 'help': 'x'}]}
    pages = app.plugins.data['pages']
    pages['bad_page'] = {'content': {'source': {'defaults': {'x': '$setting.shop.nope'}}}}
    try:
        found = {(i['code'], i['path']) for i in run_checks(app)
                 if i['severity'] in ('error', 'warning')}
    finally:
        del data['broken'], pages['bad_page']

    assert found == {
        ('setting-group-label', 'settings.broken'),
        ('setting-type', 'settings.broken.no_type'),
        ('setting-default', 'settings.broken.bad_default'),
        ('setting-help', 'settings.broken.no_help'),
        ('key-unknown', 'settings.broken.items[3].defualt'),
        ('setting-unknown', 'pages.bad_page.content.source.defaults.x'),
    }
