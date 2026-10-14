@echo off
rem Starts the Translation Manager from source (needs Python 3.9+; pywebview is optional).
rem Works from any folder:  run_manager.bat  [path\to\game\tl\czech]  [options, see README.md]
setlocal EnableExtensions
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.9 or newer was not found. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% "%~dp0progress.py" %*
if errorlevel 1 (
  echo.
  echo The program ended with an error ^(code %errorlevel%^). Details are in %%APPDATA%%\BaDIKTranslationManager\error.log if it crashed.
  pause
)
