@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Будут добавлены только два новых файла в каталог игры:
echo   game\sdv_autoload.rpy
echo   game\sdv_voice_path.txt
echo Сценарии, сохранения и архив игры не меняются.
set /p ANSWER=Введите da чтобы продолжить: 
if /I not "%ANSWER%"=="da" (
  echo Отменено.
  exit /b 1
)
if not exist "venv\Scripts\python.exe" (
  echo Сначала запустите setup.bat
  exit /b 1
)
call venv\Scripts\python.exe -m sdv.install_integration
exit /b %ERRORLEVEL%
