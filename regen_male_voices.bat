@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Сначала запустите setup.bat
  exit /b 1
)
echo Переозвучка Семёна, рассказчика, мыслей и остальных мужчин. Полный прогон в этот момент должен быть закрыт.
call venv\Scripts\python.exe -m sdv.regen_male_voices
exit /b %ERRORLEVEL%
