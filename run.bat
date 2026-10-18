@echo off
title VantaHQ Bot
cd /d "%~dp0"
py -3 bot.py
if errorlevel 1 (
  echo.
  echo Bot stopped with an error. Read the message above.
  pause
)
