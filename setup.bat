@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set "PY=%ProgramFiles%\Python312\python.exe"
if not defined PY (
  echo Не найден Python 3.12. Установите его командой:
  echo winget install --id Python.Python.3.12 -e
  exit /b 1
)
if not exist "venv\Scripts\python.exe" (
  "%PY%" -m venv venv
  if errorlevel 1 exit /b 1
)
call venv\Scripts\python.exe -m pip install --upgrade pip
call venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
if errorlevel 1 call venv\Scripts\python.exe -m pip install torch torchaudio
call venv\Scripts\python.exe -m pip install -r requirements.txt
call venv\Scripts\python.exe -m pip install -e .
call venv\Scripts\python.exe -m pip install qwen-tts --no-deps
call venv\Scripts\python.exe -m pip install hf_xet
call venv\Scripts\python.exe -m pip install "transformers==4.57.3" "accelerate==1.12.0" librosa einops
call venv\Scripts\python.exe -c "from pathlib import Path; Path(r'venv/Lib/site-packages/sox.py').write_text('class Transformer:\n    def __getattr__(self, name):\n        return lambda *args, **kwargs: self\n', encoding='utf-8')"
call venv\Scripts\python.exe -c "import torch; print('CUDA', torch.cuda.is_available())"
echo Окружение готово. Дальше: analyze.bat
exit /b 0
