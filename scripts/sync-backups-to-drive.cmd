@echo off
rem Copy Watchd's nightly backups (written into the project's backups folder
rem by the backup service, see backup.sh) to Google Drive, which uploads them.
rem Run by the "Watchd backup to Google Drive" scheduled task at 3:30am and
rem at sign-in. Docker can't write to Google Drive's G: drive itself.
set "SRC=%~dp0..\backups"
set "DEST=G:\My Drive\Watchd Backups"
if not exist "G:\My Drive" exit /b 1
robocopy "%SRC%" "%DEST%" /MIR /R:2 /W:5 /NP /NFL /NDL /LOG:"%SRC%\last-sync.log"
rem robocopy exit codes below 8 mean success.
if %ERRORLEVEL% LSS 8 exit /b 0
exit /b %ERRORLEVEL%
