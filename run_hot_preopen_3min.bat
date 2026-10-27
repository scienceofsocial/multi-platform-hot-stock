@echo off
chcp 65001 >nul
rem ===========================================================
rem  Pre-open 3-minute window chain (09:00 -> 09:26:56).
rem  Triggered by Windows Task Scheduler task: HotPreopen3Min
rem  (trigger 1: daily from 09:00, every 3 min, duration 25 min
rem              -> 09:00 09:03 ... 09:24, nine samples)
rem   trigger 2: daily 09:26:56, single shot -> the tail sample
rem   trigger 3: at logon, single shot -> the whole chain also fires
rem              right after the Administrator logs on, so a fresh
rem              sample exists without waiting until 09:00)
rem
rem  Why: the 10 min cadence of HotRankTDX_Intraday is too coarse for
rem  the call-auction window - it only ever lands on 09:00 / 09:10 /
rem  09:20, so the sj88.ld change-points table showed just three rows
rem  before the open. This task samples every 3 min instead, and renders
rem  the Markdown table + HTML board right after every sample, so
rem  a_render_ld_timeline.py's output is never more than ~3 min old in
rem  the window that actually matters.
rem
rem  Chain : run_hot_rank_daily.bat   (fetch the five platforms -> append
rem                                   the changed board to
rem                                   _hot_archive\hot_trace.jsonl ->
rem                                   rewrite the .dat files + report)
rem       -> run_hot_ld_timeline.bat (render the sj88.ld change-points
rem                                   Markdown table + the HTML board)
rem       -> run_ld_top3_blk_551883.bat
rem                                   (PROGRAM 1: append the 3 codes that
rem                                   are currently shown as the last row
rem                                   of that table into the TDX block
rem                                   blocknew\551883.blk - append only,
rem                                   run AFTER the render step on purpose
rem                                   so the trace already holds this
rem                                   slot's data point)
rem  Log   : hot_preopen_3min.log (append; the three child chains keep
rem          their own logs)
rem  NOTE  : the tail slot is RENDER-ONLY on purpose. The 09:26:56 data
rem          point is already produced by the forced 09:26:50 pass of
rem          HotRankTDX_Intraday (JYGS re-crawl, cache bypassed); running
rem          the fetch chain again here would double-crawl JYGS and the
rem          five platforms for the same minute, so this slot only
rem          refreshes the view. Detected from the wall clock, because
rem          Task Scheduler cannot pass an argument per trigger (all
rem          triggers share this one action). An explicit first argument
rem          "tail" forces the render-only path, for manual runs.
rem  NOTE  : during 09:00-09:24 this task and the 10 min cadence of
rem          HotRankTDX_Intraday both fire at 09:00 / 09:10 / 09:20. That
rem          is a harmless duplicate (same board content, so nothing is
rem          appended to hot_trace.jsonl), and neither task is modified
rem          by this one - keeping them separate means this window can be
rem          switched off without touching the all-day pipeline.
rem  NOTE  : this chain runs SILENTLY. The registered task launches it
rem          through run_hidden.vbs (wscript.exe, window style 0), so no
rem          console window appears on the desktop. The old trailing
rem          :linger is gone - it existed only to hold that window open
rem          long enough for a human to read. The principal stays
rem          InteractiveToken because the JYGS leg needs a real desktop
rem          for its Playwright/OCR pass: only the window is hidden, not
rem          the desktop.
rem  NOTE  : keep this file ASCII-only; cmd parses .bat with the ANSI
rem          codepage (non-ASCII bytes here desync the reader after
rem          chcp 65001)
rem ===========================================================
setlocal
cd /d "%~dp0"

set "LOG=%~dp0hot_preopen_3min.log"

set "TAIL="
if /i "%~1"=="tail" set "TAIL=1"
set "NOWHM=0000"
for /f "delims=" %%t in ('powershell -NoProfile -Command "(Get-Date).ToString('HHmm')" 2^>nul') do set "NOWHM=%%t"
if %NOWHM% GEQ 926 if %NOWHM% LEQ 929 set "TAIL=1"
if defined TAIL goto tail

call :log "===== START pre-open window chain (fetch + render) ====="
call "%~dp0run_hot_rank_daily.bat"
if errorlevel 1 call :log "WARN - fetch chain reported a failure, rendering whatever is on record"
call "%~dp0run_hot_ld_timeline.bat"
if errorlevel 1 call :log "WARN - render chain reported a failure"
call "%~dp0run_ld_top3_blk_551883.bat"
if errorlevel 1 call :log "WARN - PROGRAM 1 (551883 append) reported a failure"
call :log "OK - pre-open window chain done (fetch + render + 551883 append)"
exit /b 0

:tail
call :log "===== TAIL slot (09:26:56): render + PROGRAM 1 append ====="
call :log "NOTE - the data point comes from the forced 09:26:50 pass of HotRankTDX_Intraday; not re-fetching here"
call "%~dp0run_hot_ld_timeline.bat"
if errorlevel 1 call :log "WARN - render chain reported a failure"
call "%~dp0run_ld_top3_blk_551883.bat"
if errorlevel 1 call :log "WARN - PROGRAM 1 (551883 append) reported a failure"
call :log "OK - tail render done"
exit /b 0

:log
>>"%LOG%" echo [%date% %time%] %~1
exit /b 0
