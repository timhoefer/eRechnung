"""The confirmation binds a request, a browser and the exact previous state."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from confirmation_helpers import BUYER, add_other, invoice_fields, snapshot
from confirmation_helpers import client as client
from lxml import html
from werkzeug.datastructures import MultiDict

import app as m
import change_confirmation as confirmations


@pytest.fixture(autouse=True)
def fresh_confirmations(monkeypatch):
    monkeypatch.setattr(m, 'CHANGE_CONFIRMATIONS', confirmations.Confirmations())


def post(client, path, fields, token=''):
    return client.post(path, data=fields, headers={
        'X-Requested-With': 'fetch', 'X-Change-Confirmation': token,
    })


def change_case(kind):
    if kind == 'archive':
        for suffix in ('pdf', 'xml', 'json', 'csv'):
            (m.OUTPUT_DIR / f'Rechnung_1.{suffix}').write_text('original')
        return '/archive/delete', {'filename': 'Rechnung_1.pdf'}
    if kind == 'issuer':
        add_other()
        return '/issuers/delete', {'issuer': 'default', 'confirm': 'delete'}
    if kind in ('settings', 'settings/autosave'):
        return '/' + kind, {'name': 'Changed Studio', 'seller_revision': m.seller_revision(m.load_seller())}
    if kind == 'customers/delete':
        return '/' + kind, {'buyer_name': BUYER['name']}
    if kind == 'customers/items/save':
        m.CUSTOMERS_FILE.write_text(json.dumps([{**BUYER, 'items': [{'description': 'Old service'}]}]))
        return '/' + kind, {'buyer_name': BUYER['name'], 'description': 'New service',
                           'quantity': '1', 'unit_price': '100', 'unit': 'HUR'}
    return '/' + kind, {**{'buyer_' + k: v for k, v in BUYER.items()}, 'buyer_city': 'Hamburg'}


@pytest.mark.parametrize('kind', ['archive', 'issuer', 'settings', 'settings/autosave',
                                 'customers/delete', 'customers/save', 'customers/autosave', 'customers/items/save'])
def test_direct_mutations_require_matching_confirmation(client, kind):
    path, fields = change_case(kind)
    before = snapshot()
    response = post(client, path, fields)
    assert response.status_code == 428
    assert response.headers['Cache-Control'] == 'no-store'
    assert snapshot() == before
    change = response.json['confirmation']
    assert change['message'] and change['details']
    response = post(client, path, fields, change['token'])
    assert response.status_code in (200, 204, 302)
    assert snapshot() != before


def test_archive_confirmation_lists_and_deletes_entire_bundle(client):
    path, fields = change_case('archive')
    change = post(client, path, fields).json['confirmation']
    assert {d['label'] for d in change['details']} == {f'Rechnung_1.{s}' for s in ('pdf', 'xml', 'json', 'csv')}
    response = post(client, path, fields, change['token'])
    assert response.status_code == 302
    assert not list(m.OUTPUT_DIR.iterdir())


@pytest.mark.parametrize('tamper', ['request', 'state', 'other_browser', 'expiry', 'cancel', 'restart', 'forged'])
def test_old_or_unrelated_confirmation_cannot_overwrite(client, monkeypatch, tamper):
    path, fields = change_case('customers/save')
    change = post(client, path, fields).json['confirmation']
    token = change['token']
    if tamper == 'request':
        fields['buyer_city'] = 'Munich'
    elif tamper == 'state':
        m.CUSTOMERS_FILE.write_text(json.dumps([{**BUYER, 'city': 'Frankfurt'}]))
    elif tamper == 'other_browser':
        client = m.app.test_client()
    elif tamper == 'expiry':
        now = confirmations.time.monotonic()
        monkeypatch.setattr(confirmations.time, 'monotonic', lambda: now + 301)
    elif tamper == 'cancel':
        assert client.post(change['cancel_url'], data={'token': token}).status_code == 204
    elif tamper == 'restart':
        monkeypatch.setattr(m, 'CHANGE_CONFIRMATIONS', confirmations.Confirmations())
    elif tamper == 'forged':
        token = 'true'
    before = snapshot()
    response = post(client, path, fields, token)
    assert response.status_code == 428
    assert response.json['confirmation']['token'] != token
    assert snapshot() == before


def test_archive_token_cannot_be_reused_even_when_file_is_recreated(client):
    path, fields = change_case('archive')
    token = post(client, path, fields).json['confirmation']['token']
    assert post(client, path, fields, token).status_code == 302
    change_case('archive')
    assert post(client, path, fields, token).status_code == 428


def test_other_browser_cannot_cancel_issued_token(client):
    path, fields = change_case('customers/delete')
    change = post(client, path, fields).json['confirmation']
    stranger = m.app.test_client()
    assert stranger.post(change['cancel_url'], data={'token': change['token']}).status_code == 204
    assert post(client, path, fields, change['token']).json['ok']


def test_confirmation_never_authorizes_another_issuer(client):
    other = add_other()
    path, fields = change_case('settings')
    token = post(client, path, fields).json['confirmation']['token']
    fields['seller_revision'] = m.seller_revision(json.loads((other / 'seller.json').read_text()))
    assert post(client, path + '?issuer=' + other.name, fields, token).status_code == 428
    assert json.loads((other / 'seller.json').read_text())['name'] == 'Other Company'


def test_archive_changes_after_review_require_new_confirmation(client):
    path, fields = change_case('archive')
    token = post(client, path, fields).json['confirmation']['token']
    (m.OUTPUT_DIR / 'Rechnung_1.xml').write_text('newer XML')
    before = snapshot()
    assert post(client, path, fields, token).status_code == 428
    assert snapshot() == before


def test_unchanged_and_new_customer_do_not_need_confirmation(client):
    original = {'buyer_' + k: v for k, v in BUYER.items()}
    assert post(client, '/customers/save', original).json['ok']
    assert post(client, '/customers/save', {**original, 'buyer_name': 'New client'}).json['ok']


def test_normal_form_confirmation_preserves_repeated_fields_and_escapes_text(client):
    path, fields = change_case('customers/items/save')
    fields = MultiDict(fields)
    fields.add('description', '<script>alert(1)</script>')
    fields.add('quantity', '2')
    fields.add('unit', 'DAY')
    fields.add('unit_price', '200')
    response = client.post(path, data=fields)
    assert response.status_code == 428
    page = html.fromstring(response.data)
    assert not page.xpath('//script[not(@src) and contains(text(), "alert(1)")]')
    inputs = page.xpath('//form[@id="change-submit-form"]/input')
    restored = MultiDict((n.get('name'), n.get('value')) for n in inputs)
    assert restored.getlist('description') == ['New service', '<script>alert(1)</script>']
    assert client.post(path, data=restored).json['ok']


@pytest.mark.parametrize('kind', ['customers/delete', 'customers/save', 'archive'])
def test_fallback_cancel_revokes_form_without_javascript(client, kind):
    path, fields = change_case(kind)
    before = snapshot()
    page = html.fromstring(client.post(path, data=fields).data)
    cancel_button = page.xpath('//button[@form="change-cancel-form"]')[0]
    assert cancel_button.get('type') == 'submit'
    cancel = page.get_element_by_id(cancel_button.get('form'))
    cancel_fields = {n.get('name'): n.get('value') for n in cancel.xpath('./input')}
    response = client.post(cancel.get('action'), data=cancel_fields)
    assert response.status_code == 303
    assert response.headers['Location'] == '/?issuer=default'
    assert snapshot() == before
    original = MultiDict((n.get('name'), n.get('value'))
                         for n in page.xpath('//form[@id="change-submit-form"]/input'))
    # Replaying the cancelled page now requires a completely new confirmation.
    assert client.post(path, data=original).status_code == 428
    assert snapshot() == before


@pytest.mark.parametrize('back', ['https://example.org/', '//example.org/', '/archive/delete'])
def test_fallback_cancel_never_redirects_to_untrusted_target(client, back):
    path, fields = change_case('customers/delete')
    change = post(client, path, fields).json['confirmation']
    response = client.post(change['cancel_url'], data={'token': change['token'], 'back': back})
    assert response.status_code == 303
    assert response.headers['Location'] == '/'
    assert post(client, path, fields, change['token']).status_code == 428


def test_generate_cannot_silently_overwrite_existing_customer(client):
    fields = invoice_fields(client)
    fields['seller_revision'] = [m.seller_revision(m.load_seller())]
    fields['buyer_city'] = ['Hamburg']
    fields['number'] = ['TEST-1']
    fields['issue_date'] = [date.today().isoformat()]
    form = MultiDict((k, v) for k, values in fields.items() for v in values)
    before = snapshot()
    response = post(client, '/generate', form)
    assert response.status_code == 428
    assert snapshot() == before  # No customer changes, files, or counter advance.
    approved = post(client, '/generate', form, response.json['confirmation']['token'])
    assert approved.status_code == 200
    assert m.load_customers()[0]['city'] == 'Hamburg'
    assert (m.OUTPUT_DIR / 'Rechnung_TEST-1.pdf').is_file()


def test_export_cancel_page_exposes_scoped_draft_for_restoration(client):
    fields = invoice_fields(client)
    fields.update(buyer_city=['Hamburg'], number=['TEST-1'],
                  seller_revision=[m.seller_revision(m.load_seller())])
    form = MultiDict((k, v) for k, values in fields.items() for v in values)
    response = client.post('/generate?issuer=default', data=form)
    assert response.status_code == 428
    page = html.fromstring(response.data)
    cancel = page.get_element_by_id('change-cancel-form')
    assert cancel.get('data-draft-key') == f'erechnung:lang:{m.issuer_scope()}:default'
    restored = MultiDict((n.get('name'), n.get('value'))
                         for n in page.xpath('//form[@id="change-submit-form"]/input'))
    assert restored.getlist('description') == fields['description']
    assert restored['buyer_city'] == 'Hamburg'
    assert not list(m.OUTPUT_DIR.iterdir())


def test_confirmations_are_enabled_without_experimental_import(client):
    path, fields = change_case('customers/delete')
    assert post(client, path, fields).status_code == 428
    assert 'change_confirmation.js' in client.get('/').text
    assert client.get('/drafts/import').status_code == 404
    assert client.post('/drafts/open').status_code == 404


def test_only_one_concurrent_request_can_consume_confirmation():
    store = confirmations.Confirmations()
    token = store.check('', 'owner', 'data')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.check(token, 'owner', 'data'), range(2)))
    assert results.count(None) == 1


def test_pending_confirmations_are_bounded():
    store = confirmations.Confirmations(limit=2)
    first = store.check('', 'owner', 'data')
    store.check('', 'owner', 'data')
    store.check('', 'owner', 'data')
    assert store.check(first, 'owner', 'data') is not None


def test_default_normalization_does_not_prompt_for_unchanged_master_data(client):
    seller = m.load_seller()
    fields = {'name': seller['name'], 'bank_kind': 'iban', 'seller_revision': m.seller_revision(seller)}
    assert post(client, '/settings/autosave', fields).status_code == 204


@pytest.mark.parametrize('suffix', ['xml', 'json', 'csv'])
def test_orphaned_companions_are_preserved_on_export(client, suffix):
    original = m.OUTPUT_DIR / f'Rechnung_TEST-1.{suffix}'
    original.write_text('Keep this file')
    fields = invoice_fields(client)
    fields.update(number=['TEST-1'], issue_date=[date.today().isoformat()],
                  seller_revision=[m.seller_revision(m.load_seller())])
    form = MultiDict((k, v) for k, values in fields.items() for v in values)
    assert post(client, '/generate', form).status_code == 409
    assert original.read_text() == 'Keep this file'
    assert not list(m.OUTPUT_DIR.glob('*.pdf'))


def test_desktop_csv_exports_never_overwrite_existing_files(client, monkeypatch):
    monkeypatch.setitem(m.app.config, 'DESKTOP', True)
    monkeypatch.setattr(m.sys, 'platform', 'darwin')
    monkeypatch.setattr(m, 'reveal_in_finder', lambda path: None)
    first = client.get('/export/csv').json
    assert first and first['ok']
    path = m.OUTPUT_DIR / first['name']
    path.write_text('Keep my earlier export')
    second = client.get('/export/csv').json
    assert second and second['ok'] and second['name'] != first['name']
    assert path.read_text() == 'Keep my earlier export'


def test_unnamed_profile_with_existing_details_is_still_protected(client):
    seller = m.load_seller()
    seller['name'] = ''
    m.SELLER_FILE.write_text(json.dumps(seller))
    before = snapshot()
    fields = {'address_line': 'Changed street', 'seller_revision': m.seller_revision(seller)}
    assert post(client, '/settings', fields).status_code == 428
    assert snapshot() == before


def test_customer_rename_is_reviewed_and_keeps_one_record(client):
    fields = {**{'buyer_' + k: v for k, v in BUYER.items()},
              'prev_name': BUYER['name'], 'buyer_name': 'Renamed customer'}
    response = post(client, '/customers/save', fields)
    assert response.status_code == 428
    change = response.json['confirmation']
    assert any(d['before'] == BUYER['name'] and d['after'] == 'Renamed customer' for d in change['details'])
    assert m.load_customers()[0]['name'] == BUYER['name']
    assert post(client, '/customers/save', fields, change['token']).json['ok']
    assert [c['name'] for c in m.load_customers()] == ['Renamed customer']


@pytest.mark.parametrize('endpoint', ['/customers/autosave', '/customers/save'])
def test_rename_cannot_merge_two_existing_customers(client, endpoint):
    m.CUSTOMERS_FILE.write_text(json.dumps([BUYER, {**BUYER, 'name': 'Other customer', 'city': 'Hamburg'}]))
    fields = {**{'buyer_' + k: v for k, v in BUYER.items()},
              'prev_name': BUYER['name'], 'buyer_name': 'Other customer'}
    before = snapshot()
    assert post(client, endpoint, fields).status_code == 409
    assert snapshot() == before
