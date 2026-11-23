@echo off
rem Runs the card agent (answers fuel card requests in the driver groups) and starts it again if it ever stops.
rem Needs once: "main.py agent-login"; Claude runs on this PC's Claude Code login (the plan). It opens the eManager window itself and keeps its
rem login alive: log in there by hand (every 24 hours); don't run efs-login beside it. Close this window to stop.
cd /d "%~dp0"
title Card agent
:again
.venv\Scripts\python.exe src\main.py card-agent
echo The card agent stopped. Starting it again in 30 seconds (close this window to stop it for good).
timeout /t 30 /nobreak >nul
goto again
