@echo off
powershell.exe -NoProfile -Command "Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'JARVIS_AI' -ErrorAction SilentlyContinue"
