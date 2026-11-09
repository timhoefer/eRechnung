"""Test starts cannot read production configuration or move into real data."""
import json
import os
import subprocess
import sys
from pathlib import Path

import app as m


def test_test_mode_uses_new_temporary_storage_in_each_process():
    script = """
import json
import app
print(json.dumps({'base': str(app.BASE), 'data': str(app.DATA_DIR),
                  'seller': app.load_seller(), 'config': app._load_app_config(),
                  'customers': app.load_customers(), 'files': list(p.name for p in app.OUTPUT_DIR.iterdir())}))
"""
    results = []
    for _ in range(2):
        process = subprocess.run([sys.executable, '-c', script], cwd=Path(m.__file__).parent,
                                 env={**os.environ, 'ERECHNUNG_TEST_MODE': '1'},
                                 text=True, capture_output=True, check=True)
        data = json.loads(process.stdout)
        assert data['base'] == data['data']
        assert data['seller'] == {'country': 'DE'}
        assert data['config'] == {} and data['customers'] == [] and data['files'] == []
        assert not Path(data['base']).exists()  # discarded on shutdown
        results.append(data['base'])
    assert results[0] != results[1]


def test_test_mode_rejects_switching_data_folder_before_any_write(tmp_path, monkeypatch):
    root = tmp_path / 'isolated'
    root.mkdir()
    target = tmp_path / 'must-not-be-created'
    monkeypatch.setattr(m, 'TEST_MODE', True)
    monkeypatch.setattr(m, 'BASE', root)
    monkeypatch.setattr(m, 'DATA_DIR', root)
    assert m.set_data_dir(str(target)) == (False, 'test_data_dir_locked')
    assert not target.exists()
    assert m.DATA_DIR == root
    assert list(root.iterdir()) == []


def test_test_mode_ignores_configured_data_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'TEST_MODE', True)
    monkeypatch.setattr(m, 'BASE', tmp_path)
    monkeypatch.setattr(m, '_load_app_config', lambda: (_ for _ in ()).throw(AssertionError('must not read config')))
    assert m._resolve_data_dir() == tmp_path
