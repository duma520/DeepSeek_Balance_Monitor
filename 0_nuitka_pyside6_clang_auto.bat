@echo off
rem ============================================================
rem  DeepSeek Balance Monitor - Nuitka build script (PySide6 / clang)
rem ------------------------------------------------------------
rem  NOTE: keep every comment in this file ASCII-only and keep
rem  the file saved as CRLF without BOM. cmd.exe parses the file
rem  byte by byte, so UTF-8 comments would break the parser.
rem
rem  Output: build_output\DeepSeek_Balance_Monitor.dist\
rem  Distribute the WHOLE dist folder (exe + DLLs + icon.ico).
rem  NEVER ship your .env file; users create their own.
rem
rem  Set DBMS_SKIP_BUILD=1 to only validate prerequisites (dry run).
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  DeepSeek Balance Monitor - Nuitka build
echo  Working directory: %CD%
echo ============================================================
echo.

if not exist "DeepSeek_Balance_Monitor.py" (
    echo [ERROR] DeepSeek_Balance_Monitor.py not found.
    echo         Put this bat next to the main script and run it again.
    exit /b 1
)

if not exist "icon.ico" (
    echo [WARN] icon.ico not found - the exe will have no icon and the
    echo        window icon will be missing too. Run _scaffold\make_icon.py
    echo        to generate one.
    echo.
)

python -c "import PySide6, requests" 2>nul
if errorlevel 1 (
    echo [ERROR] Missing dependencies. Install them first:
    echo         pip install -r requirements.txt
    exit /b 1
)

echo [INFO] Prerequisites OK.
if defined DBMS_SKIP_BUILD (
    echo [DRY RUN] DBMS_SKIP_BUILD is set - stopping before the actual build.
    exit /b 0
)
echo.

echo [INFO] Building with Nuitka... this can take several minutes.
echo.

rem  Exclude heavy packages this program never uses. Without these
rem  exclusions the dist folder grows to hundreds of MB because Nuitka
rem  also follows OPTIONAL imports found inside third-party packages.
rem  winsdk / winotify / win10toast are optional notification accelerators:
rem  the program falls back to its built-in PowerShell WinRT channel, so
rem  they are excluded to keep the package small. Remove them from this
rem  list if you want the in-process (fastest) notification backend baked in.
rem  Keep this list in sync when new third-party imports are added.
set NUITKA_EXCLUDES=matplotlib,numpy,pandas,scipy,contourpy,kiwisolver,pyparsing,cycler,PIL,Pillow,tkinter,IPython,jupyter,jupyter_core,cryptography,lxml,pythonnet,clr_loader,pytz,markupsafe,backports,setuptools,pip,wheel,pkg_resources,test,unittest,doctest,lib2to3,distutils,venv,ensurepip,winotify,win10toast,winsdk,pymysql

python -m nuitka ^
    --standalone ^
    --assume-yes-for-downloads ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=icon.ico ^
    --include-data-files=icon.ico=icon.ico ^
    --include-package=requests ^
    --include-package=certifi ^
    --include-package-data=certifi ^
    --nofollow-import-to=%NUITKA_EXCLUDES% ^
    --follow-imports ^
    --jobs=4 ^
    --clang ^
    --remove-output ^
    --output-dir=build_output ^
    DeepSeek_Balance_Monitor.py

set NUITKA_EXIT=%ERRORLEVEL%
set NUITKA_EXCLUDES=
if not "%NUITKA_EXIT%"=="0" (
    echo.
    echo [ERROR] Nuitka build failed with exit code %NUITKA_EXIT%. Common reasons:
    echo         - an old DeepSeek_Balance_Monitor.exe is still running
    echo           (close it and retry; the linker cannot overwrite it)
    echo         - missing clang / MSVC toolchain
    exit /b 1
)

echo.
echo ============================================================
echo  Build finished.
echo  Output: %CD%\build_output\DeepSeek_Balance_Monitor.dist\
echo  Remember: distribute the whole .dist folder and keep .env out of it.
echo ============================================================
