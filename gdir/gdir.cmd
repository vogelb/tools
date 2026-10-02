@echo off
rem gdir - DIR-style listing colored by git state; starts gdir.ps1 from cmd.exe.
rem This file was created with the help of AI — model: Claude Sonnet 5.5 (model ID: claude-sonnet-5.5)
powershell -NoProfile -File "%~dp0gdir.ps1" %*
