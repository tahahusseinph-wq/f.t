@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo تجهيز البيئة لأول مرة...
  py -3.12 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe run_ftapp.py
