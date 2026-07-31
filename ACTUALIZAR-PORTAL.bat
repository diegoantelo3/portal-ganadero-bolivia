@echo off
REM Revisa si FERCOGAN subio un remate nuevo y, si lo hay, actualiza y publica
REM el portal. Lo corre solo el Programador de tareas de Windows, pero tambien
REM se puede hacer doble clic aca para forzar una actualizacion.

set PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PYEXE%" set PYEXE=python

cd /d "%~dp0"
"%PYEXE%" automation\correr_local.py
