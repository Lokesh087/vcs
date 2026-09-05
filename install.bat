@echo off
setlocal enabledelayedexpansion

REM Figure out the folder this installer lives in (works no matter where
REM the pyvcs folder was extracted/copied to on this computer).
set "INSTALL_DIR=%~dp0"
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"

echo.
echo pyvcs installer
echo ================
echo Install folder: %INSTALL_DIR%
echo.

REM Check python is available
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on this computer.
    echo Please install Python 3 from https://python.org first, then run this installer again.
    pause
    exit /b 1
)

REM Read the current user PATH from the registry
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "CURRENT_PATH=%%B"

echo !CURRENT_PATH! | find /I "%INSTALL_DIR%" >nul
if errorlevel 1 (
    if defined CURRENT_PATH (
        setx PATH "!CURRENT_PATH!;%INSTALL_DIR%" >nul
    ) else (
        setx PATH "%INSTALL_DIR%" >nul
    )
    echo Added %INSTALL_DIR% to your PATH.
) else (
    echo %INSTALL_DIR% is already in your PATH - nothing to do.
)

echo.
echo Installation complete!
echo.
echo IMPORTANT: close this window and open a NEW terminal (PowerShell or
echo Command Prompt) - PATH changes only apply to new windows.
echo.
echo Then try:
echo     vcs init
echo     vcs stage .
echo     vcs save -m "first commit"
echo.
pause
