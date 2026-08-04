@echo off
rem ===========================================================================
rem  Show Finder - double-click this file to install the program on this PC.
rem
rem  It is a thin wrapper: everything real happens in windows\install.ps1.
rem  Its whole job is to start that with an execution policy that works on a
rem  stock PC, and to keep this window open long enough to read whatever it
rem  says - a batch window that closes instantly is the classic way an
rem  installer "does nothing".
rem ===========================================================================
title Show Finder - Installer
cd /d "%~dp0"

echo.
echo   ==================================================================
echo    SHOW FINDER - INSTALLER
echo   ==================================================================
echo.
echo    Setting up. Please leave this window open.
echo.

if not exist "%~dp0windows\install.ps1" goto notextracted
if not exist "%~dp0fnscraper\cli.py"    goto notextracted

where powershell.exe >nul 2>&1
if errorlevel 1 goto nopowershell

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\install.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo   ------------------------------------------------------------------
  echo    The installer did not finish. The message above says why.
  echo    Nothing on this PC was damaged - it is safe to try again.
  echo   ------------------------------------------------------------------
  echo.
)
echo   Press any key to close this window.
pause >nul
exit /b %RC%

:notextracted
echo   ------------------------------------------------------------------
echo    The program files are not all here.
echo.
echo    This happens when the installer is started from INSIDE the ZIP
echo    file - Windows only unpacks the one file you double-click.
echo.
echo    Do this instead:
echo      1. Right-click the ZIP file you downloaded.
echo      2. Choose "Extract All..." and click Extract.
echo      3. Open the folder that appears and double-click Install there.
echo   ------------------------------------------------------------------
echo.
pause
exit /b 1

:nopowershell
echo   ------------------------------------------------------------------
echo    Windows PowerShell was not found on this PC, so the installer
echo    cannot run. This is very unusual - PowerShell ships with every
echo    supported version of Windows.
echo.
echo    Ask whoever manages this computer to enable Windows PowerShell,
echo    then double-click Install again.
echo   ------------------------------------------------------------------
echo.
pause
exit /b 1
