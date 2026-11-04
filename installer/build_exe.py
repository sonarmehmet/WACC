"""Build dist/WACC/WACC.exe with PyInstaller (Windows). Run from the repo root:  python installer/build_exe.py"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEP = os.pathsep  # ';' on Windows: --add-data SRC;DEST


def main() -> int:
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noconsole", "--name", "WACC",
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"), "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT / "hub"), "--paths", str(ROOT / "backend"), "--paths", str(ROOT / "desktop"),
        "--paths", str(ROOT / "web"),
        "--add-data", f"{ROOT / 'web' / 'public'}{SEP}web/public",
        "--add-data", f"{ROOT / 'assets'}{SEP}assets",
        "--hidden-import", "serve",
        "--collect-submodules", "wacc_hub", "--collect-submodules", "wacc_backend", "--collect-submodules", "wacc_desktop",
        "--collect-submodules", "uvicorn", "--collect-submodules", "anyio",
        str(ROOT / "launcher" / "wacc_launcher.py"),
    ]
    return subprocess.call(args, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
