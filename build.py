"""Build the Windows app folder with PyInstaller: python build.py -> dist/PhotoLUT/PhotoLUT.exe"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "PhotoLUT",
        "--add-data", f"{ROOT / 'looks'}{os.pathsep}looks",
        "--exclude-module", "tkinter",
        str(ROOT / "PhotoLUT.py"),
    ], cwd=ROOT)
    app = ROOT / "dist" / "PhotoLUT"
    for name in ("README.md", "NOTICE.md"):
        shutil.copy2(ROOT / name, app / name)
    if sys.platform == "win32":
        shutil.make_archive(str(ROOT / "dist" / "PhotoLUT-Windows-x64"), "zip", app.parent, app.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
