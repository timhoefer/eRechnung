"""Regression cases for container checks, cache migration and failed writes."""
import json
import shutil

import pytest
from lxml import html
from test_archive_selection import FILE
from test_archive_selection import archive as archive
from test_validation_status import validator as validator
from test_xml import make_data

import app as m
import validation_status as status


@pytest.mark.parametrize('changed_file', [None, 'pdf', 'json', 'csv'])
def test_identical_invoice_copy_remains_a_valid_move_target_after_recheck(archive, validator, tmp_path, changed_file):
    client, folders = archive
    old_document = folders['default'] / FILE
    old_document.with_suffix('.csv').write_bytes(b'original csv')
    client.post('/settings/panel', data={'filename': FILE})
    target = tmp_path / 'previous-copy'
    shutil.copytree(m.DATA_DIR, target)
    old_receipt = status.receipt_path(old_document).read_bytes()
    client.post('/settings/panel', data={'filename': FILE})
    assert status.receipt_path(old_document).read_bytes() != old_receipt
    assert old_document.read_bytes() == (target / 'output' / FILE).read_bytes()
    latest_receipt = status.receipt_path(old_document).read_bytes()
    original_folder = m.DATA_DIR
    if changed_file:
        (target / 'output' / FILE).with_suffix('.' + changed_file).write_bytes(b'conflicting invoice data')
    result = m.set_data_dir(str(target))
    if changed_file:
        assert result == (False, 'issuer_move_conflict')
        assert m.DATA_DIR == original_folder and old_document.is_file()
        assert status.receipt_path(target / 'output' / FILE).read_bytes() == old_receipt
        return
    assert result == (True, 'data_dir_ok'), result
    assert status.receipt_path(target / 'output' / FILE).read_bytes() == latest_receipt
    assert not old_document.exists() and not status.receipt_path(old_document).exists()
    assert not (original_folder / 'seller.json').exists()


@pytest.mark.parametrize('document_kind', ['pdf', 'xml'])
def test_manual_validation_never_marks_wrong_container_valid(archive, document_kind):
    client, folders = archive
    pdf = folders['default'] / FILE
    data = make_data()
    if document_kind == 'xml':
        sidecar = json.loads(pdf.with_suffix('.json').read_text())
        sidecar['invoice']['profile'] = 'xrechnung'
        pdf.with_suffix('.json').write_text(json.dumps(sidecar))
        data['invoice']['profile'] = 'xrechnung'
        data['buyer']['reference'] = 'TEST'
    xml = m.build_xml(data)
    assert m.validate_xml_bytes(xml)[0]
    assert m.validate_schematron(xml)['ok']
    path = pdf if document_kind == 'pdf' else pdf.with_suffix('.xml')
    # Simulate an accidental replacement with the wrong export format.
    path.write_bytes(xml if document_kind == 'pdf' else m.build_pdf('<p>Test invoice</p>', xml))
    response = client.post('/settings/panel', data={'filename': path.name})
    assert response.status_code == 200
    state = status.read(path, m.validation_ruleset())
    assert state['state'] == 'invalid', state


@pytest.mark.parametrize('endpoint', ['/settings/panel', '/validate'])
@pytest.mark.parametrize('outcome', ['valid', 'invalid', 'unavailable'])
@pytest.mark.parametrize('lang', ['de', 'en'])
def test_unwritable_cache_cannot_leave_green_after_recheck(archive, validator, monkeypatch, endpoint, outcome, lang):
    client, folders = archive
    client.set_cookie('lang', lang)
    path = folders['default'] / FILE
    client.post('/settings/panel', data={'filename': FILE})
    assert status.read(path, 'rules-1')['state'] == 'valid'
    original = {p: p.read_bytes() for p in folders['default'].iterdir() if p.suffix != '.validation'}
    monkeypatch.setattr(m, 'validate_schematron', lambda raw: {
        'available': outcome != 'unavailable', 'ok': outcome == 'valid',
        'errors': ['Invalid invoice'] if outcome == 'invalid' else [], 'warnings': [],
        'error': 'Validator could not complete' if outcome == 'unavailable' else None,
    })
    original_replace = status.os.replace
    def unavailable(source, target):
        if target == status.receipt_path(path):
            raise OSError('read-only cache')
        return original_replace(source, target)
    monkeypatch.setattr(status.os, 'replace', unavailable)
    response = client.post(endpoint, data={'filename': FILE})
    assert response.status_code == 200
    warning = m.translate(lang)['validation_save_failed']
    for page in (html.fromstring(response.text), html.fromstring(client.get(endpoint).text)):
        assert not page.xpath('//span[@class="arch-validation valid"]')
        assert warning in page.xpath('//*[@role="alert"]/text()')
    assert status.read(path, 'rules-1')['state'] == ('unsaved' if outcome == 'valid' else outcome)
    assert not status.receipt_path(path).exists()  # Cannot resurrect the old green check on restart.
    assert not list(path.parent.glob('.validation-*'))
    assert all(p.read_bytes() == raw for p, raw in original.items())
    monkeypatch.setattr(status.os, 'replace', original_replace)
    monkeypatch.setattr(m, 'validate_schematron', lambda raw: {
        'available': True, 'ok': True, 'errors': [], 'warnings': [], 'error': None,
    })
    page = html.fromstring(client.post(endpoint, data={'filename': FILE}).text)
    assert page.xpath('//span[@class="arch-validation valid"]')
    assert warning not in page.text_content()
    assert status.read(path, 'rules-1')['saved']


@pytest.mark.parametrize('target_kind', ['link', 'directory'])
def test_status_migration_never_follows_or_replaces_non_file_targets(archive, validator, tmp_path, target_kind):
    client, folders = archive
    client.post('/settings/panel', data={'filename': FILE})
    old = m.DATA_DIR
    target = tmp_path / 'target'
    shutil.copytree(old, target)
    cache = status.receipt_path(target / 'output' / FILE)
    cache.unlink()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'preserve')
    if target_kind == 'link':
        cache.symlink_to(outside)
    else:
        cache.mkdir()
    assert not m.set_data_dir(str(target))[0]
    assert m.DATA_DIR == old and (folders['default'] / FILE).is_file()
    assert outside.read_bytes() == b'preserve'
    assert cache.is_symlink() if target_kind == 'link' else cache.is_dir()


def test_status_copy_failure_keeps_both_copies_and_active_folder(archive, validator, tmp_path, monkeypatch):
    client, folders = archive
    path = folders['default'] / FILE
    client.post('/settings/panel', data={'filename': FILE})
    old = m.DATA_DIR
    target = tmp_path / 'target'
    shutil.copytree(old, target)
    previous = status.receipt_path(target / 'output' / FILE).read_bytes()
    client.post('/settings/panel', data={'filename': FILE})
    original_replace = status.os.replace
    def fail_copy(source, destination):
        if destination == status.receipt_path(target / 'output' / FILE):
            raise OSError('Disk full')
        return original_replace(source, destination)
    monkeypatch.setattr(status.os, 'replace', fail_copy)
    assert m.set_data_dir(str(target)) == (False, 'data_dir_err_write')
    assert m.DATA_DIR == old and path.is_file()
    assert status.receipt_path(target / 'output' / FILE).read_bytes() == previous
    assert not list((target / 'output').glob('.validation-*'))


def test_unsaved_status_survives_folder_move_without_inheriting_old_green(archive, validator, tmp_path, monkeypatch):
    client, _ = archive
    client.post('/settings/panel', data={'filename': FILE})
    target = tmp_path / 'target'
    shutil.copytree(m.DATA_DIR, target)
    def fail_save(*args):
        raise OSError('Disk full')
    monkeypatch.setattr(status, 'save', fail_save)
    client.post('/settings/panel', data={'filename': FILE})
    assert m.set_data_dir(str(target)) == (True, 'data_dir_ok')
    current = status.read(target / 'output' / FILE, 'rules-1')
    assert current['state'] == 'unsaved' and not current['saved']
    assert not status.receipt_path(target / 'output' / FILE).exists()


def test_unremovable_old_receipt_is_ignored_during_the_session(archive, validator, monkeypatch):
    from pathlib import Path

    client, folders = archive
    path = folders['default'] / FILE
    client.post('/settings/panel', data={'filename': FILE})
    previous = status.receipt_path(path).read_bytes()
    original_unlink = Path.unlink
    original_save = status.save
    def fail_save(*args):
        raise OSError('Folder is read-only')
    def fail_unlink(self, *args, **kwargs):
        if self == status.receipt_path(path):
            raise OSError('Folder is read-only')
        return original_unlink(self, *args, **kwargs)
    monkeypatch.setattr(status, 'save', fail_save)
    monkeypatch.setattr(Path, 'unlink', fail_unlink)
    client.post('/settings/panel', data={'filename': FILE})
    assert status.receipt_path(path).read_bytes() == previous
    page = html.fromstring(client.get('/settings/panel').text)
    assert not page.xpath('//span[@class="arch-validation valid"]')
    assert m.translate('de')['validation_save_failed'] in page.text_content()
    monkeypatch.setattr(status, 'save', original_save)
    client.post('/settings/panel', data={'filename': FILE})
    assert status.read(path, 'rules-1')['state'] == 'valid'
