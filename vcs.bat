@echo off
REM pyvcs Windows launcher.
REM %~dp0 = the folder this .bat file lives in, whatever that folder is on
REM whichever computer it's copied to. That means this file keeps working
REM correctly even if the whole pyvcs folder is renamed, moved, copied to
REM a USB drive, or extracted anywhere on someone else's machine.
python "%~dp0cli.py" %*
