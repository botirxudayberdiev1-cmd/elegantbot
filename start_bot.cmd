@echo off
chcp 65001 >nul
title Elegant Media zakaz boti
cd /d "%~dp0"
:loop
echo [%date% %time%] Bot ishga tushyapti...
".venv\Scripts\python.exe" -m bot
echo.
echo [%date% %time%] Bot to'xtadi. 10 soniyadan keyin qayta ishga tushadi (butunlay to'xtatish: oynani yoping).
"%SystemRoot%\System32\timeout.exe" /t 10 >nul
goto loop
