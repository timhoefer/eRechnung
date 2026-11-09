"""Build the drag-to-Applications image with an editable, Retina-ready background."""
import argparse
import subprocess
import tempfile
from pathlib import Path

import cairosvg
import dmgbuild

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def build_dmg(app: Path, output: Path) -> None:
    app = app.resolve()
    if app.name != "eRechnung.app" or not (app / "Contents/Info.plist").is_file():
        raise ValueError("Expected a built eRechnung.app bundle")
    with tempfile.TemporaryDirectory(prefix="erechnung-dmg-art-") as tmp:
        background = Path(tmp) / "background.tiff"
        images = []
        for scale in (1, 2):
            image = Path(tmp) / f"background-{scale}x.png"
            cairosvg.svg2png(url=str(ASSETS / "dmg-background.svg"),
                            write_to=str(image), scale=scale)
            images.append(str(image))
        subprocess.run(["tiffutil", "-cathidpicheck", *images, "-out", str(background)], check=True)
        dmgbuild.build_dmg(str(output.resolve()), "eRechnung", settings={
            "format": "UDZO",
            "filesystem": "HFS+",
            "files": [str(app)],
            "symlinks": {"Applications": "/Applications"},
            "icon": str(ASSETS / "icon.icns"),
            "background": str(background),
            "window_rect": ((160, 160), (720, 460)),
            "icon_locations": {app.name: (190, 240), "Applications": (530, 240)},
            "icon_size": 112,
            "text_size": 14,
            "default_view": "icon-view",
            "arrange_by": None,
            "show_status_bar": False,
            "show_tab_view": False,
            "show_toolbar": False,
            "show_pathbar": False,
            "show_sidebar": False,
        })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_dmg(args.app, args.output)
