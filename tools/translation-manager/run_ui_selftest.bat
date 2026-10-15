@echo off
rem Starts the app on a synthetic project and opens it in the default browser with the UI self-test (see tests\ui\serve_selftest.py).
rem The result is shown as a panel at the bottom left of the page. Close this window (or press Ctrl+C) to stop.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% tests\ui\serve_selftest.py
