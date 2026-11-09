"""Invoke the separately installed local eRechnung engine without a shell/server."""
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    config = Path(__file__).resolve().parents[1] / "runtime.json"
    try:
        runtime = json.loads(config.read_text(encoding="utf-8"))
        checkout = Path(runtime["checkout"])
        arguments = sys.argv[1:]
        if "--data-dir" not in arguments and not any(arg.startswith("--data-dir=") for arg in arguments):
            arguments = ["--data-dir", runtime["data_dir"], *arguments]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if sys.platform == "darwin":
            env.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib:/usr/local/lib")
        return subprocess.run([runtime["python"], str(checkout / "assistant_cli.py"), *arguments],
                              cwd=checkout, env=env, check=False).returncode
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "skill_setup", "message": str(exc)}}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
