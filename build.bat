@echo off
rem 一键打包发布版 exe：双击运行，或用命令行 build.bat（加 nopause 可免暂停）。
rem 版本号来自 devalarm\__init__.py 的 __version__，无需在这里修改。
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.13 并加入 PATH。
    goto :fail
)

python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo 首次打包，正在安装 PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败，请手动执行：pip install pyinstaller
        goto :fail
    )
)

rem 先跑测试，失败就不打包
python -m unittest discover -s tests
if errorlevel 1 (
    echo [错误] 单元测试未通过，已中止打包。
    goto :fail
)

python tools\build_exe.py
if errorlevel 1 (
    echo [错误] 打包失败，请查看上方输出。
    goto :fail
)

echo.
echo 打包完成，发布文件在 dist\ 目录。
if /i not "%~1"=="nopause" pause
exit /b 0

:fail
if /i not "%~1"=="nopause" pause
exit /b 1
