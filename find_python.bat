@echo off
rem Sets PY to a real python.exe (skips the Microsoft Store stub).
set "PY="
for %%P in (
  "%USERPROFILE%\anaconda3\python.exe"
  "%USERPROFILE%\miniconda3\python.exe"
  "C:\ProgramData\anaconda3\python.exe"
) do if not defined PY if exist %%P set "PY=%%~P"
if not defined PY (
  where py >nul 2>nul && for /f "delims=" %%I in ('py -c "import sys;print(sys.executable)"') do set "PY=%%I"
)
if not defined PY (
  for /f "delims=" %%I in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do if not defined PY set "PY=%%I"
)
if not defined PY (
  echo Python not found. Install Python 3.9+ from python.org and check "Add python.exe to PATH".
  pause
  exit /b 1
)
