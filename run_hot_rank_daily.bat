@echo off
chcp 65001 >nul
rem ===========================================================
rem  Five-platform hot rank -> TDX sorting indicator (data slot 1)
rem  Triggered by Windows Task Scheduler task: HotRankTDX_Intraday
rem  (repeat every 10 min, all day, every day - plus once 1 min after logon,
rem   plus once 1 min after boot, plus a forced single run at 09:26:50 every
rem   day, i.e. right before the 09:30 open)
rem  NOTE  : MultipleInstancesPolicy is Queue, so the fixed 09:26:50 run is
rem          never dropped - it queues up behind a still-running pass.
rem  NOTE  : the task runs as InteractiveToken, so it only starts when there is
rem          a logged-on desktop. Winlogon auto-logon (AutoAdminLogon=1 on this
rem          machine) boots straight into the desktop, and that is what makes
rem          the pipeline unattended. Sitting at the login screen = nothing runs.
rem  Chain : a_fetch_jygs_red.py    (refresh the JYGS red-stock cache, tolerant)
rem       -> a_fetch_hot_snapshot.py  (refresh last_good.json)
rem       -> a_archive_hot_snapshot.py (copy the snapshot to _hot_archive\hot_<date>.json
rem                                     AND append the changed snapshot to
rem                                     _hot_archive\hot_trace.jsonl, tolerant - builds
rem                                     up the history the ranking boards cannot be
rem                                     re-fetched for later)
rem       -> a_export_tdx_hot_rank.py (rewrite the .dat files + the formula txt)
rem       -> a_report_daily.py        (render the daily Markdown report, tolerant)
rem  Output: C:\new_tdx\T0002\signals\signals_user_1\<market>_<code>.dat
rem          (overwritten each run, so the .401 sorting column moves with the board)
rem        + the TDX sorting formula txt in this folder (overwritten each run)
rem        + the daily Markdown report in this folder (overwritten each run;
rem          Chinese filename "five-platform resonance_ri bao_<date>.md")
rem        + _hot_archive\hot_<date>.json (one file per trade date, overwritten
rem          during the day so the last run of the day wins)
rem        + _hot_archive\{hot,factor,report}_trace.jsonl (append-only, never
rem          overwritten; one line only when the board content actually changed,
rem          so the intraday "when did popularity move" history is kept)
rem  Log   : hot_rank_daily.log (append)
rem  NOTE  : a snapshot refresh failure is NOT fatal - the exporter falls back to the
rem          last good last_good.json, so the previous scores simply stay in place.
rem          keep this file ASCII-only; cmd parses .bat with the ANSI codepage
rem          (non-ASCII bytes here desync the reader after chcp 65001)
rem ===========================================================
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
set "LOG=%~dp0hot_rank_daily.log"
set PYTHONIOENCODING=utf-8

call :log "===== START hot rank export ====="

rem Step 1: warm the JYGS (jiuyan) red-stock cache for the current trade date
rem         (tolerant - the first run of a day does Playwright + OCR; later runs
rem          reuse the cached result, and a failure never blocks the other platforms)
rem         EXCEPTION: the forced pre-open run fired by the 09:26:50 trigger must
rem         bypass that cache and re-crawl, so the pre-open board is not built on
rem         data cached in the early morning. Task Scheduler cannot pass an
rem         argument per trigger (all four triggers share this one action), so the
rem         slot is detected here from the wall clock: HHmm 0926..0929 -> --force.
rem         An explicit first argument "force" also forces it, for manual runs.
set "JYGS_FORCE="
if /i "%~1"=="force" set "JYGS_FORCE=--force"
set "NOWHM=0000"
for /f "delims=" %%t in ('powershell -NoProfile -Command "(Get-Date).ToString('HHmm')" 2^>nul') do set "NOWHM=%%t"
if %NOWHM% GEQ 926 if %NOWHM% LEQ 929 set "JYGS_FORCE=--force"
if defined JYGS_FORCE call :log "NOTE - pre-open 09:26:50 slot: forcing a JYGS re-crawl (cache bypassed)"
call :log "RUN a_fetch_jygs_red.py %JYGS_FORCE%"
"%PY%" "a_fetch_jygs_red.py" %JYGS_FORCE% >>"%LOG%" 2>&1
if errorlevel 1 call :log "WARN - JYGS red cache refresh failed, reusing cached jygs data"

rem Step 2: refresh the five-platform snapshot (tolerant - old snapshot still usable)
call :log "RUN a_fetch_hot_snapshot.py"
"%PY%" "a_fetch_hot_snapshot.py" >>"%LOG%" 2>&1
if errorlevel 1 call :log "WARN - snapshot refresh failed, reusing existing last_good.json"

rem Step 3: archive the snapshot by trade date (tolerant - history only, the
rem         ranking boards return "today" only and cannot be re-fetched later,
rem         so this is the single place where the long-run sample grows)
call :log "RUN a_archive_hot_snapshot.py"
"%PY%" "a_archive_hot_snapshot.py" >>"%LOG%" 2>&1
if errorlevel 1 call :log "WARN - snapshot archive failed, history for this date may be missing"

rem Step 4: rewrite the TDX custom-data files + the formula txt (strict)
call :step a_export_tdx_hot_rank.py
if errorlevel 1 goto fail

rem Step 5: render the daily Markdown report (tolerant - it runs AFTER the .dat files
rem         are written, so a report failure must never abort the run)
call :log "RUN a_report_daily.py"
"%PY%" "a_report_daily.py" >>"%LOG%" 2>&1
if errorlevel 1 call :log "WARN - daily report generation failed, the .dat files are already refreshed"

call :log "OK - TDX sorting indicator refreshed + daily report rendered"
exit /b 0

:fail
call :log "FAILED - aborted, indicator NOT refreshed"
exit /b 1

:step
call :log "RUN %~1"
"%PY%" "%~1" >>"%LOG%" 2>&1
exit /b %errorlevel%

:log
>>"%LOG%" echo [%date% %time%] %~1
exit /b 0
