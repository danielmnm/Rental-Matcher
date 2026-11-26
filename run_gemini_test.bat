@echo off
rem Rental Matcher: the Gemini test (double-click, or run from any terminal).
rem Needs your key in a file named .gemini_key in this folder. It saves after every
rem request, so if it stops (the day's free quota), run it again, even the next day.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 run_gemini_test.py %*) else (python run_gemini_test.py %*)
pause
