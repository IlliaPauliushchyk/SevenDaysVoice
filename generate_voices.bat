@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Сначала запустите setup.bat
  exit /b 1
)
echo Массовая генерация начнётся только если в config\tts.json выбран движок.
call venv\Scripts\python.exe -m sdv.generate
exit /b %ERRORLEVEL%
