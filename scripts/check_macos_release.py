"""Prüft Versionsnummer, App, ZIP/DMG-Installation und Release-Signierung."""
import argparse
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def check_app(app: Path, version: str, *, unsigned: bool = False) -> None:
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleShortVersionString") != version:
        raise ValueError("App-Version stimmt nicht mit der erwarteten Release-Version überein")
    binary = app / "Contents/MacOS/eRechnung"
    arches = subprocess.check_output(["lipo", "-archs", str(binary)], text=True).split()
    if "arm64" not in arches:
        raise ValueError("Apple-Silicon-Binary fehlt")
    if not unsigned:
        subprocess.run(["codesign", "--verify", "--strict", "--deep", str(app)], check=True)
        signature = subprocess.run(["codesign", "-dvv", str(app)], check=True,
                                   capture_output=True, text=True).stderr
        if "Authority=Developer ID Application:" not in signature:
            raise ValueError("Developer-ID-Signatur fehlt (Ad-hoc-Signatur genügt nicht)")
        subprocess.run(["xcrun", "stapler", "validate", str(app)], check=True)
        subprocess.run(["spctl", "--assess", "--type", "execute", str(app)], check=True)
    subprocess.run([str(binary), "--selftest"], check=True, timeout=120)


def check_archive(archive: Path, version: str, *, unsigned: bool = False) -> None:
    # ditto repariert AppleDouble-Einträge beim Entpacken automatisch. Andere
    # Entpacker können sie als zusätzliche Dateien im signierten Bundle belassen.
    # Deshalb die ZIP-Struktur prüfen, bevor ditto den Fehler verbergen kann.
    with ZipFile(archive) as zipped:
        if any(name.startswith("eRechnung.app/")
               and any(part.startswith("._") for part in PurePosixPath(name).parts)
               for name in zipped.namelist()):
            raise ValueError("AppleDouble-Metadaten im App-Bundle: ZIP mit --sequesterRsrc packen")
    with tempfile.TemporaryDirectory(prefix="erechnung-archive-check-") as tmp:
        subprocess.run(["ditto", "-x", "-k", str(archive.resolve()), tmp], check=True)
        check_app(Path(tmp) / "eRechnung.app", version, unsigned=unsigned)


def check_dmg(dmg: Path, version: str, *, unsigned: bool = False) -> None:
    if not unsigned:
        subprocess.run(["codesign", "--verify", "--strict", str(dmg)], check=True)
        signature = subprocess.run(["codesign", "-dvv", str(dmg)], check=True,
                                   capture_output=True, text=True).stderr
        if "Authority=Developer ID Application:" not in signature:
            raise ValueError("Developer-ID-Signatur des DMG fehlt")
        subprocess.run(["xcrun", "stapler", "validate", str(dmg)], check=True)
        subprocess.run(["spctl", "--assess", "--type", "open", "--context",
                        "context:primary-signature", str(dmg)], check=True)
    with tempfile.TemporaryDirectory(prefix="erechnung-dmg-check-") as tmp:
        mount = Path(tmp) / "mounted"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen",
                        "-mountpoint", str(mount), str(dmg.resolve())], check=True)
        try:
            applications = mount / "Applications"
            if not applications.is_symlink() or applications.readlink() != Path("/Applications"):
                raise ValueError("Programme-Verknüpfung im DMG fehlt oder zeigt auf den falschen Ordner")
            if not all((mount / name).is_file() for name in (".DS_Store", ".background.tiff")):
                raise ValueError("Finder-Layout oder Hintergrund im DMG fehlt")
            # Wie beim Ziehen in Programme: die kopierte App prüfen, ohne die
            # installierte App oder persönliche Rechnungsdaten anzufassen.
            installed = Path(tmp) / "installed/eRechnung.app"
            subprocess.run(["ditto", str(mount / "eRechnung.app"), str(installed)], check=True)
            check_app(installed, version, unsigned=unsigned)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--dmg", type=Path)
    parser.add_argument("--unsigned", action="store_true",
                        help="Nur Build-CI: überspringt Signierung/Notarisierung, nicht für Releases")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("Version muss x.y.z sein")
    if not args.app and not args.archive and not args.dmg:
        parser.error("--app, --archive oder --dmg erforderlich")
    if args.app:
        check_app(args.app.resolve(), args.version, unsigned=args.unsigned)
    if args.archive:
        check_archive(args.archive, args.version, unsigned=args.unsigned)
    if args.dmg:
        check_dmg(args.dmg, args.version, unsigned=args.unsigned)
    print("Build-Prüfung bestanden" if args.unsigned else "Release-Prüfung bestanden")


if __name__ == "__main__":
    main()
