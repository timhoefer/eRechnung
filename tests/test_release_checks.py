"""Release-Gates dürfen fehlende Freigaben nicht als Erfolg behandeln."""
import importlib.util
import plistlib
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "release_checks", Path(__file__).resolve().parents[1] / "scripts/check_macos_release.py")
checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checks)


@pytest.fixture
def bundle(tmp_path):
    app = tmp_path / "eRechnung.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleShortVersionString": "1.1.1",
    }))
    return app


def test_wrong_bundle_version_stops_before_execution(bundle, monkeypatch):
    monkeypatch.setattr(checks.subprocess, "run", lambda *a, **k: pytest.fail("Must not execute"))
    with pytest.raises(ValueError, match="Version"):
        checks.check_app(bundle, "1.1.2")


@pytest.mark.parametrize("failure", ["signature", "notarization", "gatekeeper"])
def test_release_rejects_missing_approval(bundle, monkeypatch, failure):
    calls = []
    monkeypatch.setattr(checks.subprocess, "check_output", lambda *a, **k: "arm64\n")

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["codesign", "-dvv"]:
            authority = "" if failure == "signature" else "Authority=Developer ID Application: Test"
            return subprocess.CompletedProcess(command, 0, stderr=authority)
        if (failure == "notarization" and command[:2] == ["xcrun", "stapler"]
                or failure == "gatekeeper" and command[0] == "spctl"):
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(checks.subprocess, "run", run)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        checks.check_app(bundle, "1.1.1")
    assert not any("--selftest" in command for command in calls)


def test_selftest_import_uses_temporary_data_dir():
    import sys
    result = subprocess.run([sys.executable, "-c", """
import sys
sys.argv.append('--selftest')
import app
assert app.BASE != app.RESOURCE_BASE
assert app.DATA_DIR == app.BASE
assert app.CONFIG_FILE.parent == app.BASE
assert app.OUTPUT_DIR.parent == app.BASE
assert not app.SELLER_FILE.exists()
"""], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stderr
