"""一键打包 Windows 单文件 exe。

依赖 PyInstaller（仅打包需要，运行 exe 的用户不需要 Python）：

    pip install pyinstaller
    python tools/build_exe.py

产物：dist/DevAlarm-V<版本>-win64.exe
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from devalarm import APP_AUTHOR, APP_NAME, APP_TITLE, __version__  # noqa: E402

DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
ICON = ROOT / "assets" / "devalarm.ico"
BUILT = DIST / f"{APP_NAME}.exe"
ASSET = DIST / f"{APP_NAME}-V{__version__}-win64.exe"


def version_tuple() -> tuple[int, int, int, int]:
    parts = [int(p) for p in __version__.split(".")]
    parts += [0] * (4 - len(parts))
    return tuple(parts[:4])  # type: ignore[return-value]


def write_version_file() -> Path:
    """生成 Windows 文件属性里的版本信息（右键 → 属性 → 详细信息）。"""
    v = version_tuple()
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v},
    prodvers={v},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [
          StringStruct('CompanyName', '{APP_AUTHOR}'),
          StringStruct('FileDescription', '{APP_TITLE}'),
          StringStruct('FileVersion', '{__version__}'),
          StringStruct('InternalName', '{APP_NAME}'),
          StringStruct('LegalCopyright', 'Copyright (C) 2026 {APP_AUTHOR}'),
          StringStruct('OriginalFilename', '{ASSET.name}'),
          StringStruct('ProductName', '{APP_TITLE}'),
          StringStruct('ProductVersion', '{__version__}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    path = ROOT / "build" / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    if shutil.which(sys.executable) is None:
        print("找不到 Python 解释器", file=sys.stderr)
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先执行：pip install pyinstaller", file=sys.stderr)
        return 1

    if not ICON.exists():
        print("图标不存在，正在生成…")
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")], check=True)

    if not (ROOT / "assets" / "alert.wav").exists():
        print("铃声不存在，正在生成…")
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_sound.py")], check=True)

    version_file = write_version_file()
    DIST.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON),
        "--version-file",
        str(version_file),
        "--add-data",
        f"{ROOT / 'assets'};assets",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
        str(ROOT / "main.py"),
    ]
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    if ASSET.exists():
        ASSET.unlink()
    BUILT.replace(ASSET)
    size_mb = ASSET.stat().st_size / 1024 / 1024
    print(f"\n打包完成：{ASSET}（{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
