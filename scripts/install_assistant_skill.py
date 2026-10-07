"""Install/remove only the optional eRechnung skill; never touch app/user data."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Read-only source data (use demo data for a trial)")
    parser.add_argument("--skills-dir", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    target = args.skills_dir.expanduser() / "erechnung"
    if args.uninstall:
        if target.is_symlink() or not (target / "runtime.json").is_file():
            parser.error("No installation made by this installer was found.")
        runtime = json.loads((target / "runtime.json").read_text())
        if runtime.get("installer") != "erechnung-local-skill-v1":
            parser.error("This skill was not installed by this installer.")
        shutil.rmtree(target)
        print(json.dumps({"ok": True, "removed": str(target)}))
        return 0
    if args.data_dir is None or not (args.data_dir.expanduser() / "seller.json").is_file():
        parser.error("Provide --data-dir with an existing seller.json.")
    if target.exists() or target.is_symlink():
        parser.error("Skill already exists; no files were changed.")
    checkout = Path(__file__).resolve().parents[1]
    shutil.copytree(checkout / "integrations" / "codex" / "erechnung", target)
    runtime = {"installer": "erechnung-local-skill-v1", "checkout": str(checkout),
               "python": sys.executable, "data_dir": str(args.data_dir.expanduser().resolve())}
    (target / "runtime.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "skill": str(target), "data_dir": runtime["data_dir"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
