@echo off
chcp 65001 >nul
rem ===========================================================
rem  Eastmoney "leading concept boards" (ling zhang gai nian) launcher.
rem  Triggered by Windows Task Scheduler task: EMLeadConcept
rem  (see register_em_concept_task.ps1 - NOT registered yet).
rem
rem  INDEPENDENT of run_hot_rank_daily.bat: its output does NOT feed the
rem  five-platform popularity pipeline, and that pipeline never reads this
rem  output either. Kept separate on purpose.
rem
rem  Chain : em_cookie.py --ensure
rem            make sure em_cookie.json is usable; extraction is skipped while
rem            the saved file is younger than the ttl (default 6h) and a
rem            failure falls back to the already saved file (tolerant)
rem       -> em_lead_concept.py -n 10 --json _em_lead_concept.json
rem            fs=m:90+t:3 (concept boards), top 10 by change pct,
rem            overwrites today's single file (STRICT - abort on failure).
rem            Tries push2 first, then falls back to push2test when push2
rem            path-blocks /api/qt/clist/get (see URLS in em_lead_concept.py).
rem       -> copy the same payload to _em_lead_concept_<yyyy-MM-dd>.json
rem            per-date archive, last run of the day wins (tolerant)
rem  Log   : em_concept_daily.log (append, this folder)
rem
rem  NOTE  : push2 rejects plain requests / httpx / curl.exe by TLS fingerprint;
rem          only curl_cffi (impersonate) gets through, and a real EM cookie
rem          raises the success rate a lot - that is what em_cookie.py provides.
rem  NOTE  : push2 also path-blocks /api/qt/clist/get at times (curl 56, 0.0s)
rem          while the same host serves /api/qt/ulist.np/get fine; that is why
rem          em_lead_concept.py keeps a second host (push2test) in URLS.
rem  NOTE  : keep this file ASCII-only; cmd parses .bat with the ANSI codepage
rem          (non-ASCII bytes here desync the reader after chcp 65001).
rem ===========================================================
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
set "LOG=%~dp0em_concept_daily.log"
set PYTHONIOENCODING=utf-8

call :log "===== START EM lead-concept capture ====="

rem Step 1: obtain / refresh the anti-bot cookie (tolerant)
call :log "RUN em_cookie.py --ensure"
"%PY%" "em_cookie.py" --ensure >>"%LOG%" 2>&1
if errorlevel 1 call :log "WARN - cookie refresh failed, reusing the saved em_cookie.json"

rem Step 2: fetch the top-10 concept boards, overwrite today's single file
call :log "RUN em_lead_concept.py -n 10 --json _em_lead_concept.json"
"%PY%" "em_lead_concept.py" -n 10 --json "_em_lead_concept.json" >>"%LOG%" 2>&1
if errorlevel 1 goto fail

rem Step 3: per-date archive copy
set "DAY="
for /f "delims=" %%d in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd')" 2^>nul') do set "DAY=%%d"
if not defined DAY set "DAY=unknown"
copy /y "_em_lead_concept.json" "_em_lead_concept_%DAY%.json" >nul 2>&1
if errorlevel 1 call :log "WARN - per-date archive copy failed (%DAY%)"

call :log "OK - lead concepts refreshed (_em_lead_concept.json + _em_lead_concept_%DAY%.json)"
exit /b 0

:fail
call :log "FAILED - aborted, _em_lead_concept.json NOT refreshed"
exit /b 1

:log
>>"%LOG%" echo [%date% %time%] %~1
exit /b 0
