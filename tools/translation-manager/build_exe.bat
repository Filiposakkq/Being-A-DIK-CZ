@echo off
rem Builds BaDIKTranslationManager.exe (no Python needed to RUN it). Double-click this file or run it from any folder.
rem   build_exe.bat            run the tests, then build
rem   build_exe.bat /notest    build without running the tests
rem Result: dist\BaDIKTranslationManager.exe (next to this file). Copy it anywhere - it remembers the translation folder.
setlocal EnableExtensions
pushd "%~dp0" || (echo Cannot enter the script folder "%~dp0". & pause & exit /b 1)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.9 or newer was not found. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^).
  goto :fail
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
  echo This build needs Python 3.9 or newer.
  goto :fail
)

if /i not "%~1"=="/notest" (
  echo [1/3] Running tests ...
  %PY% -m unittest discover -s tests
  if errorlevel 1 (
    echo.
    echo The tests failed - the exe was NOT built. Fix the failures or run: build_exe.bat /notest
    goto :fail
  )
) else (
  echo [1/3] Tests skipped.
)

echo [2/3] Installing build tools ...
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail
%PY% -m pip install --upgrade pywebview
if errorlevel 1 (
  echo.
  echo Warning: pywebview could not be installed - the exe will open in an Edge/Chrome app window instead.
)

echo [3/3] Building ...
%PY% -m PyInstaller --noconfirm --clean BaDIKTranslationManager.spec
if errorlevel 1 goto :fail
if not exist "dist\BaDIKTranslationManager.exe" goto :fail

echo.
echo Done: %CD%\dist\BaDIKTranslationManager.exe
echo Start it anywhere. On first start it asks for the translation folder (game\tl\czech) and remembers it.
popd
pause
exit /b 0

:fail
echo.
echo Something failed - see the messages above.
popd
pause
exit /b 1
