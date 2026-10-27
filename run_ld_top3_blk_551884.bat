@echo off
chcp 65001 >nul
rem ===========================================================
rem  PROGRAM 2 : three fixed slots per day
rem  09:00:09 / 09:20:06 / 09:26:56, plus one at logon.
rem  Append the 3 codes that are CURRENTLY SHOWN as the last row
rem  of the a_render_ld_timeline.py change-points table into the
rem  TDX block  blocknew\55188.blk  (append only - existing
rem  members are never removed, duplicates are allowed).
rem
rem  Trigger : its own task, "HotLdTop3Blk" (register_ld_top3_blk_task.ps1)
rem            with three single-shot daily triggers plus one at logon,
rem            so it also fires right after the Administrator logs on.
rem  Chain   : (read-only) _hot_archive\hot_trace.jsonl
rem            -> a_export_ld_top3_blk.py --blk ...\55188.blk
rem  Output  : C:\new_tdx\T0002\blocknew\55188.blk (appended)
rem  Log     : hot_ld_top3_blk.log (append; shared with program 1)
rem  NOTE    : this program ONLY collects - it does not fetch any board
rem            and does not re-render the table (the md/html are kept
rem            fresh by HotRankTDX_Intraday + HotLdTimeline).
rem  NOTE    : blocknew\55188.blk is SHARED with a_export_tdx_hot_rank.py,
rem            which rewrites the whole file only on its FIRST pass of the
rem            day (clearing it once) and APPENDS on every later 10-min
rem            pass. This program always appends and never rewrites, so
rem            the two no longer fight over the file.
rem  NOTE    : the launcher name still says 551884 so the already registered
rem            task keeps pointing at the same file; the target block is
rem            55188.blk - blocknew\551884.blk is no longer used.
rem  NOTE    : this chain runs SILENTLY. The registered task launches it
rem            through run_hidden.vbs (wscript.exe, window style 0), so no
rem            console window appears on the desktop. The old trailing
rem            :linger is gone - it existed only to hold that window open
rem            long enough for a human to read. The principal stays
rem            InteractiveToken (same as HotPreopen3Min), so only the
rem            window is hidden, not the desktop.
rem  NOTE    : keep this file ASCII-only; cmd parses .bat with the ANSI
rem            codepage (non-ASCII bytes here desync the reader after
rem            chcp 65001)
rem ===========================================================
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
set "LOG=%~dp0hot_ld_top3_blk.log"
set "BLK=C:\new_tdx\T0002\blocknew\55188.blk"
set PYTHONIOENCODING=utf-8

call :log "===== START program 2 (55188 append of the shown top3) ====="
"%PY%" "%~dp0a_export_ld_top3_blk.py" --blk "%BLK%" >>"%LOG%" 2>&1
if errorlevel 1 goto fail
call :log "OK - 55188.blk updated"
exit /b 0

:fail
call :log "FAILED - 55188.blk NOT updated"
exit /b 1

:log
>>"%LOG%" echo [%date% %time%] %~1
exit /b 0
