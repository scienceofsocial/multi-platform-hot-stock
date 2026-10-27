@echo off
chcp 65001 >nul
rem ===========================================================
rem  Aggregate the 55188 "leading stock board" (sj88.ld) change-
rem  points history into the four statistics that actually matter
rem  (rhythm / form / leaders / size) and rewrite the report.
rem  Triggered by Windows Task Scheduler task: HotLdTimelineStats
rem  (at startup +2min, daily 15:10 and 17:20 - AFTER the markdown
rem   table has been re-rendered by run_hot_ld_timeline.bat / HotLdTimeline)
rem  Chain : (read-only) the daily change-points Markdown in this folder
rem          + _hot_archive\hot_*.json + C:\new_tdx\vipdoc\*.day
rem          -> ld_timeline_stats.py
rem          -> out\ld_timeline_stats.md (+ .json)
rem  Flags : --json --picks (full range) so the report also carries the
rem          pick-rule section (traded days / empty days / threshold
rem          sensitivity) on every run.
rem  Log   : hot_ld_timeline_stats.log (append)
rem  NOTE  : this bat only aggregates, it never fetches boards.
rem          Keep this file ASCII-only (non-ASCII bytes here
rem          desync cmd after chcp 65001).
rem ===========================================================
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
set "LOG=%~dp0hot_ld_timeline_stats.log"
set PYTHONIOENCODING=utf-8

call :log "===== START ld timeline stats ====="
"%PY%" "ld_timeline_stats.py" --json --picks 1970-01-01:9999-12-31 >>"%LOG%" 2>&1
if errorlevel 1 goto fail
call :log "OK - statistics report refreshed in out/"
exit /b 0

:fail
call :log "FAILED - stats report NOT refreshed"
exit /b 1

:log
>>"%LOG%" echo [%date% %time%] %~1
exit /b 0