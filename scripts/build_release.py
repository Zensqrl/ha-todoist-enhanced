"""Build a deterministic manual-install archive containing runtime files only."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "todoist_enhanced"


def main():
    """Package integration without local status, tests, credentials or caches."""
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    destination = ROOT / "dist" / f"todoist-enhanced-{version}.zip"
    destination.parent.mkdir(exist_ok=True)
    paths = sorted(
        path
        for path in COMPONENT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in {".py", ".json", ".yaml"}
    )
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in paths:
            info = ZipInfo(path.relative_to(ROOT).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(paths)
    print(f"Built {destination} ({len(paths)} runtime files)")


if __name__ == "__main__":
    main()
