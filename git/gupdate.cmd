@echo off
rem gupdate - Update child Git repositories; starts gupdate.ps1 from cmd.exe.
rem This file was created with the help of AI — model: GPT-6.1 Sol (model ID: gpt-6.1-sol)
powershell -NoProfile -File "%~dp0gupdate.ps1" %*
