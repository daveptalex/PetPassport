@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Execute primeiro setup_windows.bat
  exit /b 1
)
call .venv\Scripts\activate.bat
flet doctor
flet build apk --python-version 3.12 --product "Pet Passport" --org "pt.petpassport" --project pet_passport
flet build aab --python-version 3.12 --product "Pet Passport" --org "pt.petpassport" --project pet_passport
echo APK em build\apk e AAB em build\aab
endlocal
