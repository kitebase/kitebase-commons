"""
The plugin on a Kitebase application: registry, loader, view, resolver, and
`reports.run` through the download route.

The application is built once for the module: the shared plugins common, users
and reports, plus `shop`, written here, with a virtual column, a relation, two
report loops, templates in its `andrep/` folder and an installation layer.
"""
import importlib.util
import io
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

pytest.importorskip("andrep.adapters.sqlalchemy")

import kitebase.plugins  # noqa: E402
import kitebase.source  # noqa: E402
import kitebase.utils  # noqa: E402
from kitebase import access  # noqa: E402
from kitebase.endpoints import FileResult  # noqa: E402
from kitebase.server_utils import handle_download, handle_generic_endpoint  # noqa: E402

from helpers import make_template  # noqa: E402

COMMONS = Path(__file__).resolve().parents[3] / 'plugins'

SHOP_MODEL = {
    'tables': {
        'Customer': {'name': 'customers', 'columns': [
            {'name': 'id', 'type': 'Integer', 'primary_key': True, 'autoincrement': True},
            {'name': 'first_name', 'type': 'String', 'length': 50},
            {'name': 'last_name', 'type': 'String', 'length': 50},
            {'name': 'full_name', 'type': 'String', 'virtual': True},
        ]},
        'Order': {'name': 'orders', 'columns': [
            {'name': 'id', 'type': 'Integer', 'primary_key': True, 'autoincrement': True},
            {'name': 'number', 'type': 'String', 'length': 20},
            {'name': 'customer_id', 'type': 'Integer',
             'foreign_key': {'target': 'Customer.id'}},
        ]},
    },
}

SHOP_PY = '''
from sqlalchemy.ext.hybrid import hybrid_property


class Customer:
    @hybrid_property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
'''

SHOP_REPORTS = '''
from andrep import AndRepRenderer

from kitebase import access
from reports.registry import load_records, report


class Counting(AndRepRenderer):
    def on_init(self):
        self.count = 0

    def on_after_band(self, band_name):
        self.count += 1


@report('shop.customers', table='Customer', label='Customers', renderer=Counting,
        options='customer_options')
def customers(r, params):
    for row in load_records('Customer', params['ids'], load=['orders']):
        r.emit('band')


@report('shop.cards', table='Customer', on_empty='row', options='card_options',
        access='shop.print_cards')
def cards(r, params):
    for row in load_records('Customer', params['ids']):
        r.emit('band')


@report('shop.clash', table='Order', options='clash_options')
def clash(r, params):
    r.emit('band')


@report('shop.users')
def users(r, params):
    for row in load_records('User', params['ids']):
        r.emit('band')


@report('shop.ledger')
def ledger(r, params):
    for row in load_records('Customer', params['ids']):
        with access.system():
            row.orders            # the orders, read on purpose beyond the user's permissions
        r.emit('band')


@report('shop.side_customer', input='none', params={'side': 'customer'})
@report('shop.side_supplier', input='none', params={'side': 'supplier'})
def side(r, params):
    side = params['side']
    r.emit('band')


@report('shop.resources', input='none')
def resources(r, params):
    ref = params['options']['ref']
    r.emit('band')
'''


SHOP_VIEWS = {'views': {
    'customer_options': {'type': 'form', 'source': {}, 'layout': [
        {'type': 'section', 'id': 'options', 'fields': [
            {'name': 'with_orders', 'type': 'Boolean', 'default': True}]}]},
    'card_options': {'type': 'form', 'source': {}, 'presentation': 'page', 'layout': [
        {'type': 'section', 'id': 'options', 'fields': [
            {'name': 'owner_id', 'type': 'Integer', 'foreign_key': {'target': 'User.id'}}]}]},
    'clash_options': {'type': 'form', 'source': {}, 'layout': [
        {'type': 'section', 'id': 'options', 'fields': [{'name': 'title', 'type': 'String'}]}]},
}}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('shopapp')
    shop = root / 'plugins' / 'shop'
    shop.mkdir(parents=True)
    (shop / 'config.yaml').write_text(yaml.safe_dump(
        {'name': 'shop', 'depends_on': ['common', 'users', 'reports']}))
    (shop / 'model.yaml').write_text(yaml.safe_dump(SHOP_MODEL))
    (shop / 'model.py').write_text(SHOP_PY)
    (shop / 'shop_reports.py').write_text(textwrap.dedent(SHOP_REPORTS))
    (shop / 'views.yaml').write_text(yaml.safe_dump(SHOP_VIEWS))

    andrep = shop / 'andrep'
    write_json(andrep / 'customers.json', make_template(
        {'band': ['[row.full_name]', '[row.last_name]', "[', '.join(o.number for o in row.orders)]"],
         'page_footer': ['[_r.count]']}, name='Customers'))
    write_json(andrep / 'customers_wide.json', make_template({'band': ['[row.id]']}))
    write_json(andrep / 'shop.customers_short.json', make_template({'band': ['[row.id]']}))
    write_json(andrep / 'cards.json', make_template({'band': ['[row.id]']}))
    write_json(andrep / 'ledger.json', make_template(
        {'band': ["[', '.join(o.number for o in row.orders)]"]}))
    write_json(andrep / 'clash.json', make_template({'band': ['x']}))
    write_json(andrep / 'users.json', make_template({'band': ['[row.username]', '[row.password]']}))
    write_json(andrep / 'side_customer.json', make_template({'band': ['[side]']}))
    write_json(andrep / 'side_supplier.json', make_template({'band': ['[side]']}))
    write_json(andrep / 'resources.json', make_template({'band': ["[ref | load]"]}))
    (andrep / 'logo.txt').write_text('a public asset')
    write_json(andrep / 'other.json', make_template({'band': ['other']}))
    std = [{'rule': 'InsBefore', 'target': 'standard_header'}]
    write_json(andrep / 'customers_headed.json', make_template(
        {'band': ['[row.id]']}, composition=std))
    landscape = [{'rule': 'InsBefore', 'target': 'standard_header_landscape'}]
    write_json(andrep / 'customers_landscape.json', make_template(
        {'band': ['[row.id]']}, composition=landscape))
    (root / 'secret.txt').write_text('outside every root')

    installation = root / '_andrep'
    write_json(installation / 'customers_wide.json', make_template({'band': ['[row.last_name]']}))
    write_json(installation / 'customers_store.json', make_template({'band': ['[row.first_name]']}))
    write_json(installation / 'standard_header_landscape.json',
               make_template({'page_header': ['installed header [_r.name[0]]']}))

    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'shopapp',
        'plugins': [{'path': str(COMMONS), 'include': ['common', 'users', 'reports']},
                    'plugins'],
        'db_engine': f'sqlite:///{root / "shop.sqlite"}',
        'reports': {'header': ['Example Trading Ltd', 'VAT 00000000000']},
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

        with db.get_session() as s:
            ada = model.Customer(first_name='Ada', last_name='Byron')
            alan = model.Customer(first_name='Alan', last_name='Turing')
            s.add_all([ada, alan,
                       model.Order(number='A1', customer=ada),
                       model.Order(number='A2', customer=ada),
                       model.User(name='Admin', username='admin', password='admin',
                                  email='admin@example.com')])
            s.commit()
        yield db
    finally:
        os.chdir(cwd)


def run(app, **data):
    """reports.run through the download route: a FileResult, or the error dict."""
    return handle_download(app.cp, 'reports.run', data, {'username': 'tester', 'id': 1})


def press_print(app, **data):
    """reports.print through the dispatcher: the body the client applies."""
    return handle_generic_endpoint(app.cp, 'reports.print', data, {'username': 'tester', 'id': 1})


def rows(result):
    """The values of the `row` bands of a JSON result."""
    assert isinstance(result, FileResult), result
    return [rec['values'] for rec in json.loads(result.content) if rec['band'] == 'band']


# ── Registry ──────────────────────────────────────────────────────────────────

def test_the_plugin_loops_are_registered(app):
    from reports import registry
    assert {'shop.customers', 'shop.users', 'shop.side_customer',
            'shop.side_supplier'} <= set(registry.all_reports())


def test_a_name_outside_the_plugin_domain_is_refused(app):
    from reports import registry
    with pytest.raises(ValueError, match="must start with 'shop.'"):
        registry.register('sales.list', lambda r, p: None, domain='shop')


def test_a_name_without_a_domain_is_refused(app):
    from reports import registry
    with pytest.raises(ValueError, match="not 'domain.name'"):
        registry.register('list', lambda r, p: None, domain='shop')


def test_registering_a_name_twice_needs_replace(app):
    from reports import registry

    def first(r, p): pass

    def second(r, p): pass

    registry.register('shop.twice', first, domain='shop')
    with pytest.raises(ValueError, match='replace=True'):
        registry.register('shop.twice', second, domain='shop')
    assert registry.register('shop.twice', second, domain='shop', replace=True).loop is second


def test_the_decorator_takes_the_domain_from_the_module(app):
    from reports import registry

    def loop(r, p): pass
    loop.__module__ = 'sales.reports'
    with pytest.raises(ValueError, match="must start with 'sales.'"):
        registry.report('shop.stolen')(loop)


def test_the_catalog_of_a_table_is_its_reports_in_order(app):
    from reports import registry
    catalog = registry.for_table('Customer')
    assert [r.name for r in catalog] == ['shop.customers', 'shop.cards']
    assert [r.title for r in catalog] == ['Customers', 'cards']
    assert registry.for_table('Partner') == []


def test_one_loop_under_two_names_gets_each_its_params(app):
    assert rows(run(app, report='shop.side_customer', format='json')) == [['customer']]
    assert rows(run(app, report='shop.side_supplier', format='json')) == [['supplier']]


# ── Records ───────────────────────────────────────────────────────────────────

def test_rows_come_in_the_order_asked(app):
    assert rows(run(app, report='shop.customers', ids=[2, 1], format='json')) == [
        ['Alan Turing', 'Turing', ''], ['Ada Byron', 'Byron', 'A1, A2']]


def test_an_id_that_matches_nothing_is_skipped(app):
    assert rows(run(app, report='shop.customers', ids=[99, 1], format='json')) == [
        ['Ada Byron', 'Byron', 'A1, A2']]


def test_the_renderer_subclass_is_the_one_registered(app):
    result = run(app, report='shop.customers', ids=[1, 2], format='json')
    footer = [rec for rec in json.loads(result.content) if rec['band'] == 'page_footer']
    assert footer and footer[-1]['values'] == [2]


def test_a_secret_column_is_not_a_field(app):
    [[username, password]] = rows(run(app, report='shop.users', ids=[1], format='json'))
    assert username == 'admin'
    assert 'password' in str(password) and 'admin' not in str(password)


def test_load_names_relations_only(app):
    from reports.registry import load_records
    with app.get_session() as s, pytest.raises(ValueError, match="no relation 'number'"):
        list(load_records('Customer', [1], load=['orders.number'], session=s))


# ── Templates ─────────────────────────────────────────────────────────────────

def test_the_variants_are_the_files_with_the_report_prefix(app):
    from reports.context import LayeredLoader, plugin_layers
    from reports.endpoints import variants
    from reports import registry

    loader = LayeredLoader(plugin_layers(app.pm))
    assert variants(registry.get('shop.customers'), loader) == [
        'customers', 'customers_headed', 'customers_landscape', 'customers_store',
        'customers_wide', 'shop.customers_short']


def test_the_installation_layer_wins(app):
    assert rows(run(app, report='shop.customers', ids=[1], template='customers_wide',
                    format='json')) == [['Byron']]


def test_a_variant_born_in_production_runs(app):
    assert rows(run(app, report='shop.customers', ids=[1], template='customers_store',
                    format='json')) == [['Ada']]


def test_the_domain_prefixed_variant_runs(app):
    assert rows(run(app, report='shop.customers', ids=[1], template='shop.customers_short',
                    format='json')) == [[1]]


def html_of(app, template, **data):
    result = run(app, report='shop.customers', ids=[1], template=template, format='html', **data)
    assert isinstance(result, FileResult), result
    return result.content.decode('utf-8')


def test_the_standard_header_comes_from_the_reports_plugin(app):
    html = html_of(app, 'customers_headed', title='Our customers')
    for text in ('Example Trading Ltd', 'VAT 00000000000', 'Our customers',
                 'customers_headed'):      # the template it was printed with
        assert text in html
    assert '[#' not in html                # the lines config.yaml leaves out print empty


def test_the_installation_restyles_a_shared_part(app):
    html = html_of(app, 'customers_landscape')
    assert 'installed header Example Trading Ltd' in html


@pytest.mark.parametrize('template', ['other', '../config', 'users', '/etc/passwd'])
def test_a_template_outside_the_report_is_refused(app, template):
    result = run(app, report='shop.customers', ids=[1], template=template, format='json')
    assert result['status_code'] == 400
    assert 'is not a template of report' in result['message']


@pytest.mark.parametrize('name', ['../config', 'a/b', '.hidden', ''])
def test_the_loader_refuses_names_that_are_not_file_names(app, name):
    from reports.context import LayeredLoader, plugin_layers
    with pytest.raises(ValueError):
        LayeredLoader(plugin_layers(app.pm)).load(name)


# ── Resources ─────────────────────────────────────────────────────────────────

def resource(app, ref):
    """The document printing `[ref | load]` of `@ref`: formatters run when it is built."""
    result = run(app, report='shop.resources', ref='@' + ref, format='html')
    assert isinstance(result, FileResult), result
    return result.content.decode('utf-8')


def test_a_public_root_is_readable(app):
    assert 'a public asset' in resource(app, 'shop:logo.txt')


@pytest.mark.parametrize('ref', [
    'secret.txt',                      # relative: the default resolver reads the cwd
    'shop:../../../secret.txt',
    'uploads:x.txt',                   # a root that is not public
    'https://example.com/logo.png',
])
def test_anything_else_is_refused(app, ref):
    value = resource(app, ref)
    assert 'outside every root' not in value
    assert '[#' in value


# ── The endpoint ──────────────────────────────────────────────────────────────

def test_pdf_opens_html_and_json_are_saved(app):
    pdf = run(app, report='shop.customers', ids=[1], format='pdf')
    html = run(app, report='shop.customers', ids=[1], format='html')
    assert (pdf.mime, pdf.disposition) == ('application/pdf', 'inline')
    assert pdf.content.startswith(b'%PDF')
    assert (html.mime, html.disposition) == ('text/html', 'attachment')
    assert b'Ada Byron' in html.content


@pytest.mark.parametrize('data, message', [
    ({'report': 'shop.nope', 'ids': [1]}, 'Unknown report'),
    ({'report': 'shop.customers', 'ids': [1], 'format': 'docx'}, 'Unknown report format'),
    ({'report': 'shop.customers', 'ids': []}, 'No rows to print'),
    ({'report': 'shop.customers', 'ids': 1}, 'ids must be a list'),
])
def test_what_cannot_run_is_refused(app, data, message):
    result = run(app, **data)
    assert result['status_code'] == 400
    assert message in result['message']


def test_options_arrive_flat_beside_what_run_reads(app):
    from reports import registry
    seen = {}

    def loop(r, params):
        seen.update(params)
        r.emit('band')

    registry.register('shop.side_customer', loop, domain='shop', input='none',
                      params={'side': 'customer'}, replace=True)
    try:
        run(app, report='shop.side_customer', format='json', title='T', with_orders=False)
    finally:
        registry.register('shop.side_customer', registry.get('shop.side_supplier').loop,
                          domain='shop', input='none', params={'side': 'customer'}, replace=True)
    assert seen['options'] == {'with_orders': False}


# ── The Print button ──────────────────────────────────────────────────────────

def test_a_table_with_several_reports_answers_a_menu(app):
    body = press_print(app, table='Customer', id=1, view_ids=[2, 1])['data']
    assert body['action'] == 'choose'
    assert [o['label'] for o in body['options']] == ['Customers', 'cards']
    then = body['options'][0]['then']
    assert then == {'action': 'endpoint', 'op': 'reports.print',
                    'params': {'table': 'Customer', 'id': 1, 'view_ids': [2, 1],
                               'report': 'shop.customers'}}


def test_the_picked_report_answers_its_dialog(app):
    body = press_print(app, table='Customer', id=1, view_ids=[2, 1], report='shop.customers')['data']
    assert body['action'] == 'form'
    view = body['view']
    assert view['presentation'] == 'dialog'
    names = [f['name'] for s in view['layout'] for f in s['fields']]
    assert names == ['template', 'title', 'format', 'with_orders']
    template = view['layout'][0]['fields'][0]
    assert {c['value'] for c in template['choices']} >= {'customers', 'customers_wide',
                                                        'customers_store', 'shop.customers_short'}
    labels = {c['value']: c['label'] for c in template['choices']}
    assert labels['customers'] == 'Customers (customers)'    # the template's title
    assert labels['customers_wide'] == 'customers_wide'      # no title: the file
    assert body['values'] == {'template': 'customers', 'title': 'Customers', 'format': 'pdf',
                              'with_orders': True}
    assert body['then'] == {'action': 'download', 'op': 'reports.run',
                            'params': {'report': 'shop.customers', 'ids': [2, 1]}}


def test_the_ticked_rows_win_over_the_screen(app):
    body = press_print(app, table='Customer', ids=[1], view_ids=[2, 1],
                       report='shop.customers')['data']
    assert body['then']['params']['ids'] == [1]


def test_a_card_prints_the_current_row_and_its_form_says_page(app):
    body = press_print(app, table='Customer', id=2, view_ids=[2, 1], report='shop.cards')['data']
    assert body['then']['params']['ids'] == [2]
    assert body['view']['presentation'] == 'page'


def test_what_the_dialog_sends_runs(app):
    body = press_print(app, table='Customer', view_ids=[2, 1], report='shop.customers')['data']
    result = run(app, **body['then']['params'], **{**body['values'], 'format': 'json'})
    assert [r[1] for r in rows(result)] == ['Turing', 'Byron']


@pytest.mark.parametrize('data, message', [
    ({'table': 'Customer', 'report': 'shop.customers'}, 'No rows to print'),
    ({'table': 'Customer', 'report': 'shop.users', 'ids': [1]}, 'Unknown report'),
    ({'table': 'Order', 'ids': [1]}, "'title' of report 'shop.clash' uses a reserved name"),
])
def test_what_cannot_be_printed_is_refused(app, data, message):
    result = press_print(app, **data)
    assert result['status_code'] == 400
    assert message in result['message']


def test_a_table_without_reports_says_so(app):
    body = press_print(app, table='User', ids=[1])['data']
    assert body == {'message': 'Nothing to print here'}


def test_the_spreadsheet_is_one_row_per_band_with_typed_values(app):
    from openpyxl import load_workbook
    result = run(app, report='shop.customers', template='shop.customers_short',
                 ids=[2, 1], format='xlsx')
    assert result.disposition == 'attachment'
    sheet = load_workbook(io.BytesIO(result.content)).active
    rows = [list(r) for r in sheet.iter_rows(values_only=True) if r[0] == 'band']
    assert rows == [['band', 2], ['band', 1]]


def sheet_rows(result) -> list:
    from openpyxl import load_workbook
    return [list(r) for r in load_workbook(io.BytesIO(result.content)).active.iter_rows(values_only=True)]


def test_a_post_processor_writes_the_spreadsheet(app):
    from reports import registry

    def table(records, book):
        sheet = book.active
        sheet.append(['Id'])
        for rec in records:
            if rec['band'] == 'band':
                sheet.append(rec['values'])

    def only_one(records, book):
        book.active.append(['just this template'])

    registry.register_post('shop.customers', table)
    registry.register_post('shop.customers', only_one, template='customers_wide')
    try:
        short = run(app, report='shop.customers', template='shop.customers_short',
                    ids=[2, 1], format='xlsx')
        wide = run(app, report='shop.customers', template='customers_wide', ids=[1],
                   format='xlsx')
        assert sheet_rows(short) == [['Id'], [2], [1]]
        assert sheet_rows(wide) == [['just this template']]
        with pytest.raises(ValueError, match='replace=True'):
            registry.register_post('shop.customers', only_one)
    finally:
        registry._POSTS.clear()
    raw = run(app, report='shop.customers', template='shop.customers_short', ids=[1],
              format='xlsx')
    assert [r for r in sheet_rows(raw) if r[0] == 'band'] == [['band', 1]]


def test_a_post_processor_is_for_a_known_format(app):
    from reports import registry
    with pytest.raises(ValueError, match='format must be one of'):
        registry.register_post('shop.customers', lambda records, book: None, format='pdf')


# ── Access: the loop reads for the user ──────────────────────────────────────

class Denying(access.Guard):
    def __init__(self, denied):
        self.denied = set(denied)

    def allows(self, permission, context):
        return permission not in self.denied

    def allows_undeclared(self, endpoint, context):
        return True


@pytest.fixture
def denied():
    def deny(*permissions):
        access._GUARD = Denying(permissions)
    yield deny
    access._GUARD = access.OPEN


def test_a_table_the_user_cannot_read_stops_the_print(app, denied):
    denied('Customer.read')
    result = run(app, report='shop.customers', ids=[1], format='json')
    assert result['status_code'] == 403
    assert "'Customers'" in result['message'] and 'Customer.read' in result['message']


def test_a_relation_read_by_the_template_is_checked_too(app, denied):
    denied('Order.read')
    result = run(app, report='shop.customers', ids=[1], format='json')
    assert result['status_code'] == 403
    assert 'Order.read' in result['message']


def test_system_reads_what_the_report_means_to_show(app, denied):
    denied('Order.read')
    assert rows(run(app, report='shop.ledger', ids=[1], format='json')) == [['A1, A2']]


def test_the_permission_of_a_report_comes_before_its_loop(app, denied):
    denied('shop.print_cards')
    result = run(app, report='shop.cards', ids=[1], format='json')
    assert result['status_code'] == 403
    assert "'cards'" in result['message']


def test_the_print_button_offers_what_the_user_may_print(app, denied):
    denied('shop.print_cards')
    body = press_print(app, table='Customer', id=1, view_ids=[2, 1])['data']
    assert body['action'] == 'form'                       # one report left: its dialog
    assert body['then']['params']['report'] == 'shop.customers'
