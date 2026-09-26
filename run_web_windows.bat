@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Execute primeiro setup_windows.bat
  exit /b 1
)
call .venv\Scripts\activate.bat
set FLET_WEB_NO_CDN=1
flet run --web
endlocal
