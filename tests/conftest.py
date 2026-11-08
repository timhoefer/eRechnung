"""Isolate app startup before test modules import it or read local config."""
import os

import pytest

# Even an unmocked app import must never load real invoices or advance counters.
os.environ['ERECHNUNG_TEST_MODE'] = '1'


@pytest.fixture(autouse=True)
def allow_fixture_data_directories(monkeypatch):
    import app

    # Route fixtures supply their own tmp_path folders; migration tests must be
    # able to switch between them. The app's initial BASE is already temporary.
    monkeypatch.setattr(app, 'TEST_MODE', False)
