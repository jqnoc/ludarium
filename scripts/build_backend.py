from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__


ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build" / "backend"
WORK_DIR = BUILD_DIR / "work"
SPEC_DIR = BUILD_DIR / "spec"
EXE_NAME = "ludarium-backend"


def main() -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for path in (WORK_DIR, SPEC_DIR):
        if path.exists():
            shutil.rmtree(path)

    separator = ";" if os.name == "nt" else ":"
    PyInstaller.__main__.run([
        "--noconfirm",
        "--clean",
        "--onefile",
        f"--name={EXE_NAME}",
        f"--distpath={BUILD_DIR}",
        f"--workpath={WORK_DIR}",
        f"--specpath={SPEC_DIR}",
        f"--add-data={ROOT / 'static'}{separator}static",
        f"--add-data={ROOT / 'templates'}{separator}templates",
        "--collect-all=PIL",
        str(ROOT / "app.py"),
    ])

    suffix = ".exe" if os.name == "nt" else ""
    executable = BUILD_DIR / f"{EXE_NAME}{suffix}"
    if not executable.exists():
        raise FileNotFoundError(f"Expected backend executable was not created: {executable}")
    print(f"Built {executable}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Backend build failed: {exc}", file=sys.stderr)
        raise
