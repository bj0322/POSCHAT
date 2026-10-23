@echo off
REM SPDX-FileCopyrightText: 2026 Beomjoon Kim
REM SPDX-License-Identifier: AGPL-3.0-only
rem Builds release\PostechChat-Setup.exe with python.org Python (not Anaconda) in .buildenv
cd /d "%~dp0"
if not exist ".buildenv\Scripts\python.exe" (
  where py >nul 2>nul || (echo Install Python 3.10+ from python.org first. & pause & exit /b 1)
  py -3 -m venv .buildenv || (pause & exit /b 1)
  ".buildenv\Scripts\python.exe" -m pip install -q -r requirements.txt pyinstaller || (pause & exit /b 1)
)
".buildenv\Scripts\python.exe" build_installer.py
pause
