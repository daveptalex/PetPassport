@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Execute primeiro setup_windows.bat
  exit /b 1
)
call .venv\Scripts\activate.bat
flet build web --no-cdn --python-version 3.12 --product "Pet Passport" --project pet_passport --pwa-theme-color "#2F6F62" --pwa-background-color "#F5FAF8"
if errorlevel 1 exit /b 1
echo Web/PWA offline build: build\web
endlocal
