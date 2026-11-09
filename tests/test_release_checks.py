"""Release-Gates dürfen fehlende Freigaben nicht als Erfolg behandeln."""
import importlib.util
import json
import plistlib
import subprocess
import textwrap
from pathlib import Path
from zipfile import ZipFile

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


def test_archive_rejects_metadata_inside_framework_before_extraction(tmp_path, monkeypatch):
    archive = tmp_path / "eRechnung.app.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("eRechnung.app/Contents/Frameworks/Python.framework/._Python", b"metadata")
    monkeypatch.setattr(checks.subprocess, "run", lambda *a, **k: pytest.fail("Must not extract"))
    with pytest.raises(ValueError, match="AppleDouble"):
        checks.check_archive(archive, "1.1.3")


def test_archive_accepts_sequestered_metadata_and_checks_bundle(tmp_path, monkeypatch):
    archive = tmp_path / "eRechnung.app.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("eRechnung.app/Contents/Info.plist", b"placeholder")
        zipped.writestr("__MACOSX/eRechnung.app/Contents/Frameworks/Python.framework/._Python",
                        b"metadata")
    commands = []
    bundles = []
    monkeypatch.setattr(checks.subprocess, "run", lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(checks, "check_app", lambda app, version, **kw: bundles.append(
        (app, version, kw)))
    checks.check_archive(archive, "1.1.3")
    assert commands[0][:3] == ["ditto", "-x", "-k"]
    assert bundles == [(Path(commands[0][-1]) / "eRechnung.app", "1.1.3", {"unsigned": False})]


@pytest.mark.parametrize("failure", ["signature", "notarization", "gatekeeper"])
def test_dmg_rejects_missing_approval_before_mounting(tmp_path, monkeypatch, failure):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["codesign", "-dvv"]:
            authority = "" if failure == "signature" else "Authority=Developer ID Application: Test"
            return subprocess.CompletedProcess(command, 0, stderr=authority)
        if (failure == "notarization" and command[:2] == ["xcrun", "stapler"]
                or failure == "gatekeeper" and command[0] == "spctl"):
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(checks.subprocess, "run", run)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        checks.check_dmg(tmp_path / "eRechnung.dmg", "1.2.1")
    assert not any(command[0] == "hdiutil" for command in commands)


@pytest.mark.parametrize("failure", [None, "shortcut", "layout", "app", "copy"])
def test_dmg_checks_installed_copy_and_always_detaches(tmp_path, monkeypatch, failure):
    commands = []
    bundles = []
    mount = None

    def run(command, **kwargs):
        nonlocal mount
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            assert "-readonly" in command and "-nobrowse" in command
            mount = Path(command[command.index("-mountpoint") + 1])
            (mount / "Applications").symlink_to("/wrong" if failure == "shortcut" else "/Applications")
            (mount / ".DS_Store").touch()
            if failure != "layout":
                (mount / ".background.tiff").touch()
        if failure == "copy" and command[0] == "ditto":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    def check_app(app, version, **kwargs):
        assert app != mount / "eRechnung.app"
        assert app.name == "eRechnung.app" and app.parent.name == "installed"
        bundles.append((app, version, kwargs))
        if failure == "app":
            raise ValueError("App-Version")

    monkeypatch.setattr(checks.subprocess, "run", run)
    monkeypatch.setattr(checks, "check_app", check_app)
    if failure:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            checks.check_dmg(tmp_path / "eRechnung.dmg", "1.2.1", unsigned=True)
    else:
        checks.check_dmg(tmp_path / "eRechnung.dmg", "1.2.1", unsigned=True)
        assert len(bundles) == 1 and bundles[0][1:] == ("1.2.1", {"unsigned": True})
    assert commands[-1] == ["hdiutil", "detach", str(mount)]
    if failure in {"shortcut", "layout", "copy"}:
        assert not bundles


@pytest.mark.parametrize("case", ["both", "legacy", "empty", "missing_dmg", "changed_dmg", "changed_zip", "duplicate"])
def test_publish_requires_every_verified_download(monkeypatch, case):
    """Exercise the actual publish gate without allowing any GitHub writes."""
    archive = "eRechnung.app.zip"
    dmg = "eRechnung.dmg"
    expected = {archive: "sha256:zip", dmg: "sha256:dmg"}
    if case == "legacy":
        expected.pop(dmg)
    if case == "empty":
        expected = {}
    assets = [{"name": name, "digest": digest} for name, digest in expected.items()]
    if case == "missing_dmg":
        assets = [asset for asset in assets if asset["name"] != dmg]
    if case in {"changed_dmg", "changed_zip"}:
        changed = dmg if case == "changed_dmg" else archive
        next(asset for asset in assets if asset["name"] == changed)["digest"] = "sha256:changed"
    if case == "duplicate":
        assets.append(assets[0].copy())
    monkeypatch.setenv("RELEASE_TAG", "v1.2.1")
    monkeypatch.setenv("HAS_DMG", "false" if case == "legacy" else "true")
    monkeypatch.setenv("EXPECTED_DIGESTS", json.dumps(expected))
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: json.dumps({"assets": assets}))
    published = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: published.append(cmd))
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/release-check.yml").read_text()
    source = textwrap.dedent(workflow.rsplit("python - <<'PY'\n", 1)[1].split("\n          PY")[0])
    if case in {"both", "legacy"}:
        exec(compile(source, "release-check-publish", "exec"), {})
        assert published == [["gh", "release", "edit", "v1.2.1", "--draft=false", "--latest"]]
    else:
        with pytest.raises(SystemExit):
            exec(compile(source, "release-check-publish", "exec"), {})
        assert not published
