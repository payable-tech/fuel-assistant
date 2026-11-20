@echo off
rem Runs the fuel assistant (dashboard + automatic refreshes) and starts it again if it ever stops.
rem Windows opens this at logon through the "Fuel assistant" shortcut in the Startup folder. Close the window to stop.
cd /d "%~dp0"
title Fuel assistant
:again
.venv\Scripts\python.exe src\main.py serve
echo The fuel assistant stopped. Starting it again in 30 seconds (close this window to stop it for good).
timeout /t 30 /nobreak >nul
goto again
