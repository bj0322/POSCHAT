@echo off
REM SPDX-FileCopyrightText: 2026 Beomjoon Kim
REM SPDX-License-Identifier: AGPL-3.0-only
rem Run from source (for development). End users should use release\PostechChat-Setup.exe.
cd /d "%~dp0"
call "%~dp0find_python.bat" || exit /b 1
"%PY%" -c "import webview, requests, truststore" 2>nul || (
  "%PY%" -m pip install -q -r requirements.txt || "%PY%" -m pip install -q --use-feature=truststore -r requirements.txt
)
for %%D in ("%PY%") do set "PYW=%%~dpDpythonw.exe"
if exist "%PYW%" (start "" "%PYW%" main.py) else (start "" "%PY%" main.py)
