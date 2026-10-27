@echo off
chcp 65001 >nul
rem ===========================================================
rem  Render the 55188 "leading stock board" (sj88.ld) intraday
rem  change-points table into a standalone Markdown file, plus a
rem  self-refreshing HTML board off the very same trace.
rem  Triggered by Windows Task Scheduler task: HotLdTimeline
rem  (trigger 1: at boot, then every 10 min for 24 h;
rem   trigger 2: daily from 00:00, every 10 min, duration 1 day)
rem  Chain : (none - read-only) _hot_archive\hot_trace.jsonl
rem          -> a_render_ld_timeline.py  (Markdown table)
rem          -> a_view_ld_timeline.py    (HTML board, same rows/order,
rem                                       plus names/ranks and auto-refresh)
rem  Output: the Markdown table and the HTML board in this folder
rem          (both overwritten each run)
rem  Log   : hot_ld_timeline.log (append)
rem  NOTE  : hot_trace.jsonl is appended by a_archive_hot_snapshot.py, which
rem          runs inside run_hot_rank_daily.bat (task HotRankTDX_Intraday).
rem          This task only READS that trace and re-renders the table, it
rem          never fetches any board, so the two tasks never hammer the same
rem          upstream sites. The flip side: if the fetch pipeline stops, this
rem          table simply freezes at the last recorded change - one single
rem          source of truth, on purpose.
rem  NOTE  : the output filename is built by the Python script, not here -
rem          keep this file ASCII-only; cmd parses .bat with the ANSI codepage
rem          (non-ASCII bytes here desync the reader after chcp 65001)
rem ===========================================================
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
set "LOG=%~dp0hot_ld_timeline.log"
set PYTHONIOENCODING=utf-8

call :log "===== START ld change-points render ====="
call :step a_render_ld_timeline.py
if errorlevel 1 goto fail
call :step a_view_ld_timeline.py
if errorlevel 1 goto fail
call :log "OK - ld change-points markdown + html board refreshed"
exit /b 0

:fail
call :log "FAILED - ld change-points markdown/html NOT refreshed"
exit /b 1

:step
call :log "RUN %~1"
"%PY%" "%~1" >>"%LOG%" 2>&1
exit /b %errorlevel%

:log
>>"%LOG%" echo [%date% %time%] %~1
exit /b 0
