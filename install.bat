@echo off
rem Rental Matcher: set up the helper Chrome starts by itself (run once).
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m rental_matcher.install --deps %*) else (python -m rental_matcher.install --deps %*)
pause
