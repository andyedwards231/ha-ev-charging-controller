"""Build a reproducible manual-install archive from the standalone repository."""

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT / "custom_components" / "ev_charge_controller"
VERSION = json.loads((COMPONENT / "manifest.json").read_text())["version"]


def build_archive() -> Path:
    """Include runtime files and public installation documentation only."""
    destination = ROOT / "dist" / f"ev-charge-controller-{VERSION}.zip"
    destination.parent.mkdir(exist_ok=True)
    files = [
        path for path in COMPONENT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        and path.suffix != ".pyc" and not path.name.startswith(".")
    ]
    files += [ROOT / name for name in (
        "README.md", "SETUP.md", "MIGRATION.md", "VERIFICATION.md", "hacs.json",
        "docs/dashboard.md", "examples/dashboard.yaml",
    )]
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(
                path.relative_to(ROOT).as_posix(), date_time=(2026, 10, 24, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return destination


if __name__ == "__main__":
    print(build_archive())
