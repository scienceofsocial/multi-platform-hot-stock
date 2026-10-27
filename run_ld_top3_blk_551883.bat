@echo off
chcp 65001 >nul
rem ===========================================================
rem  PROGRAM 1 : pre-open 3 min grid (09:00 -> 09:26:56).
rem  Append the 3 codes that are CURRENTLY SHOWN as the last row
rem  of the a_render_ld_timeline.py change-points table into the
rem  TDX block  blocknew\551883.blk  (append only - existing
rem  members are never removed, duplicates are allowed).
rem
rem  Trigger : NOT its own task. Folded into run_hot_preopen_3min.bat
rem            (task HotPreopen3Min: daily 09:00 + every 3 min for
rem            25 min -> 09:00 09:03 ... 09:24, plus a 09:26:56 tail)
rem            and called there AFTER the fetch+render chain, so the
rem            trace already holds this slot's data point.
rem  Chain   : (read-only) _hot_archive\hot_trace.jsonl
rem            -> a_export_ld_top3_blk.py --blk ...\551883.blk
rem  Output  : C:\new_tdx\T0002\blocknew\551883.blk (appended)
rem  Log     : hot_ld_top3_blk.log (append)
rem  NOTE    : program 2 (run_ld_top3_blk_551884.bat) shares the very
rem            same engine and the same log, only the target block and
rem            the trigger times differ.
rem  NOTE    : blocknew\55188.blk is owned by a_export_tdx_hot_rank.py
rem            (full rewrite every 10 min) - this program never writes it.
rem  NOTE    : keep this file ASCII-only; cmd parses .bat with the ANSI
rem            codepage (non-ASCII bytes here desync the reader after
rem            chcp 65001)
rem ===========================================================
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
set "LOG=%~dp0hot_ld_top3_blk.log"
set "BLK=C:\new_tdx\T0002\blocknew\551883.blk"
set PYTHONIOENCODING=utf-8

call :log "===== START program 1 (551883 append of the shown top3) ====="
"%PY%" "%~dp0a_export_ld_top3_blk.py" --blk "%BLK%" >>"%LOG%" 2>&1
if errorlevel 1 goto fail
call :log "OK - 551883.blk updated"
exit /b 0

:fail
call :log "FAILED - 551883.blk NOT updated"
exit /b 1

:log
>>"%LOG%" echo [%date% %time%] %~1
exit /b 0
