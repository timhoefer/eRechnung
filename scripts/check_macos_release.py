"""Prüft Versionsnummer, App, ZIP-Roundtrip und optional Release-Signierung."""
import argparse
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path


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
    with tempfile.TemporaryDirectory(prefix="erechnung-archive-check-") as tmp:
        subprocess.run(["ditto", "-x", "-k", str(archive.resolve()), tmp], check=True)
        check_app(Path(tmp) / "eRechnung.app", version, unsigned=unsigned)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--unsigned", action="store_true",
                        help="Nur Build-CI: überspringt Signierung/Notarisierung, nicht für Releases")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("Version muss x.y.z sein")
    if not args.app and not args.archive:
        parser.error("--app oder --archive erforderlich")
    if args.app:
        check_app(args.app.resolve(), args.version, unsigned=args.unsigned)
    if args.archive:
        check_archive(args.archive, args.version, unsigned=args.unsigned)
    print("Build-Prüfung bestanden" if args.unsigned else "Release-Prüfung bestanden")


if __name__ == "__main__":
    main()
