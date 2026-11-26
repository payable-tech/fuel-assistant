@echo off
rem The card checker: reads each ACTIVE card's truck group and saves whether the card should be on. Changes nothing.
rem Windows' Task Scheduler starts it at 07:00, 13:00 and 19:00 on this PC's clock (Eastern): 6, 12 and 18 Central.
rem Needs once: "main.py checker-login". Its log: data\checker.log.
cd /d "%~dp0"
title Card checker
.venv\Scripts\python.exe src\main.py card-check
rem The task opens this in a window that stays open after the last line, and Windows then counts the run as
rem still going and skips the next one (the 13:00 run on 2026-11-26): exit closes the window.
exit
