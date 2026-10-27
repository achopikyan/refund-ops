@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run.py --restart %*
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3.13 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    py -3.13 run.py --restart %*
    goto done
  )
  py -3.12 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    py -3.12 run.py --restart %*
    goto done
  )
)
python run.py --restart %*
:done
set "launch_result=%errorlevel%"
if not "%launch_result%"=="0" (
  echo.
  echo Install Python 3.12 or 3.13 and Node.js 22.12+ or 24 LTS if missing.
  echo The error above explains why the application could not start.
  pause
)
exit /b %launch_result%
