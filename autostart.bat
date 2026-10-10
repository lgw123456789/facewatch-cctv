@echo off
rem Starts FaceWatch in the background (no window) every time you log in to Windows.
rem Run "autostart.bat off" to stop that.
cd /d "%~dp0"
set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\FaceWatch.lnk"

if /i "%~1"=="off" (
  if exist "%LINK%" del "%LINK%"
  echo FaceWatch will no longer start with Windows.
  goto :done
)

set "TARGET=%~dp0.venv\Scripts\pythonw.exe"
set "FOLDER=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK); $s.TargetPath = $env:TARGET; $s.Arguments = 'server.py'; $s.WorkingDirectory = $env:FOLDER; $s.Save()"
echo FaceWatch will now start in the background whenever you log in to Windows.
echo To start it right now without logging out, run start.bat.

:done
pause
