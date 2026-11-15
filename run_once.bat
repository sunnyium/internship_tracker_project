@echo off
REM ---------------------------------------------------------------------------
REM One sweep of every configured company AND every configured GitHub job-board
REM repo, then exit. This is what Windows Task Scheduler runs - see the "Running
REM it on a schedule" section of README.md.
REM
REM Both halves run inside run.py and produce a single email and a single push,
REM career-page results first, GitHub repo results second, and anything both
REM halves found listed once with the repeats collected under Duplicates. There
REM is nothing to add here to cover the GitHub half - it is part of the round.
REM
REM Why a .bat rather than pointing Task Scheduler straight at python.exe:
REM   - Task Scheduler's "Start in" field is easy to leave blank, and a blank
REM     one makes the working directory C:\Windows\System32, where the tracker
REM     package isn't importable. The cd below makes that impossible to get
REM     wrong.
REM   - It pins the venv interpreter. This machine has several Pythons and only
REM     the venv has the dependencies.
REM   - It captures output to a log, which is the only record of an unattended
REM     run.
REM ---------------------------------------------------------------------------

REM %~dp0 is the folder holding this file, with a trailing backslash.
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"

REM One log per month. Rounds are timestamped inside the file, and monthly
REM files keep it browsable without needing log rotation.
set STAMP=
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM"') do set STAMP=%%d
REM If PowerShell is unavailable or blocked by policy, fall back to one file
REM rather than writing to "tracker-.log".
if "%STAMP%"=="" set STAMP=undated

.venv\Scripts\python.exe run.py --once >> "data\logs\tracker-%STAMP%.log" 2>&1

REM Hand the exit code to Task Scheduler so "Last Run Result" is meaningful:
REM 0x0 = the round finished, 0x1 = it raised before finishing.
exit /b %ERRORLEVEL%
